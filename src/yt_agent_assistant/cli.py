from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from .config import EXAMPLE_CONFIG_PATH, DEFAULT_CONFIG_PATH, Settings, dump_settings, load_settings
from .services.audio import AudioEngine
from .services.images import ImageRepository, human_mb
from .services.titles import TitleService, write_refs_lists
from .services.resolve import sync_timelines
from .web_app import create_app

console = Console()
app = typer.Typer(help="YouTube vibes assistant CLI", no_args_is_help=True)


def _load_settings(path: Optional[Path]) -> Settings:
    return load_settings(path)


@app.command("init-config")
def init_config(
    destination: Path = typer.Option(DEFAULT_CONFIG_PATH, "--dest", help="Path to write config YAML."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite if file exists."),
):
    """
    Copy the example YAML config to a writable location.
    """
    if destination.exists() and not overwrite:
        typer.echo(f"[WARN] {destination} already exists. Use --overwrite to replace it.")
        raise typer.Exit(code=1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    dump_settings(load_settings(EXAMPLE_CONFIG_PATH), destination)
    typer.echo(f"Wrote config to {destination}")


titles_app = typer.Typer(help="Title generation and scripture references.")
app.add_typer(titles_app, name="titles")


@titles_app.command("generate")
def generate_titles(
    image: Path = typer.Argument(..., exists=True, help="Thumbnail image path."),
    mode: str = typer.Option("style", "--mode", "-m", help="style|devotional|click|guided"),
    instruction: str = typer.Option("", "--instruction", "-i", help="Required for guided mode."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="YAML config path."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output txt file path."),
    write_refs: bool = typer.Option(False, "--refs", help="Also write scripture reference lists."),
):
    settings = _load_settings(config)
    repo = ImageRepository(settings)
    repo.ensure_dirs()
    service = TitleService(settings)

    if mode.lower() == "style":
        titles = service.style_titles(image)
    elif mode.lower() == "devotional":
        titles = service.devotional_titles(image)
    elif mode.lower() == "click":
        titles = service.click_titles(image)
    elif mode.lower() == "guided":
        if not instruction.strip():
            typer.echo("Guided mode requires --instruction text.")
            raise typer.Exit(code=1)
        titles = service.guided_titles(image, instruction)
    else:
        typer.echo("Unknown mode. Use one of: style, devotional, click, guided.")
        raise typer.Exit(code=1)

    dest_dir = output.parent if output else repo.subdir_for_image(image)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = output or (dest_dir / f"titles_{mode.lower()}.txt")
    dest.write_text("\n".join(titles), encoding="utf-8")

    table = Table(title="Generated titles")
    table.add_column("#", justify="right")
    table.add_column("Title")
    for idx, t in enumerate(titles, start=1):
        table.add_row(str(idx), t)
    console.print(table)
    console.print(f"[bold green]Saved[/bold green] -> {dest}")

    if write_refs and titles:
        gospels, psalms, combined = service.best_references(image, titles[0])
        write_refs_lists(dest_dir, gospels, psalms, combined)
        console.print(f"[bold blue]Refs written[/bold blue] -> {dest_dir}")


@titles_app.command("refs")
def refs(
    image: Path = typer.Argument(..., exists=True, help="Thumbnail image path."),
    title: str = typer.Option(..., "--title", "-t", help="Chosen title to ground references."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="YAML config path."),
    output_dir: Optional[Path] = typer.Option(None, "--output", "-o", help="Directory for ref files."),
):
    settings = _load_settings(config)
    repo = ImageRepository(settings)
    repo.ensure_dirs()
    service = TitleService(settings)
    gospels, psalms, combined = service.best_references(image, title)
    dest_dir = output_dir or repo.subdir_for_image(image)
    write_refs_lists(dest_dir, gospels, psalms, combined)
    console.print(f"[bold green]References saved[/bold green] -> {dest_dir}")


audio_app = typer.Typer(help="Audio playlist selection and export.")
app.add_typer(audio_app, name="audio")


@audio_app.command("build")
def build_audio(
    timeline: int = typer.Option(1, "--timeline", "-t", help="Timeline index used for file suffix."),
    target_seconds: Optional[float] = typer.Option(None, "--target-seconds", help="Override target duration."),
    head: List[str] = typer.Option([], "--head", "-h", help="Preferred psalm numbers or gospel refs."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="YAML config path."),
):
    settings = _load_settings(config)
    repo = ImageRepository(settings)
    repo.ensure_dirs()
    engine = AudioEngine(settings)

    result = engine.build_playlist(timeline_idx=timeline, target_seconds=target_seconds, preferred_head=head)

    table = Table(title=f"Playlist timeline {timeline}")
    table.add_column("#", justify="right")
    table.add_column("Label")
    table.add_column("Duration (s)", justify="right")
    for idx, (_, dur, label) in enumerate(result.tracks_with_meta, start=1):
        table.add_row(str(idx), label, f"{dur:.1f}")
    console.print(table)
    console.print(f"[bold green]Track dir[/bold green]: {result.track_dir}")
    console.print(f"[bold green]Chapters[/bold green]: {result.chapters_path}")
    console.print(f"Total seconds: {result.total_seconds:.1f}")


images_app = typer.Typer(help="Image ingestion and housekeeping.")
app.add_typer(images_app, name="images")


@images_app.command("import")
def import_images(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="YAML config path."),
):
    settings = _load_settings(config)
    repo = ImageRepository(settings)
    repo.ensure_dirs()
    console.print(f"[bold green]Images ready in[/bold green]: {repo.image_dir}")


@images_app.command("yt-thumb")
def make_thumb(
    image: Path = typer.Argument(..., exists=True, help="Image to compress for YouTube."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="YAML config path."),
):
    settings = _load_settings(config)
    repo = ImageRepository(settings)
    repo.ensure_dirs()
    dst, orig, new = repo.ensure_yt_thumbnail(image)
    if dst:
        console.print(f"[bold green]YouTube thumb[/bold green]: {dst} ({human_mb(orig)} -> {human_mb(new or 0)})")
    else:
        console.print("[red]Failed to build thumbnail[/red]")


@images_app.command("reset")
def reset_outputs(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="YAML config path."),
):
    settings = _load_settings(config)
    repo = ImageRepository(settings)
    repo.hard_reset_state()
    console.print(f"[bold yellow]Outputs reset[/bold yellow] under {repo.output_dir} and {repo.track_root}")


resolve_app = typer.Typer(help="DaVinci Resolve sync and automation.")
app.add_typer(resolve_app, name="resolve")


@resolve_app.command("sync")
def resolve_sync(
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="YAML config path."),
    only: List[int] = typer.Option([], "--only", "-o", help="Timeline indices to sync (repeatable)."),
):
    settings = _load_settings(config)
    only_indices = [int(x) for x in only] if only else None
    sync_timelines(settings, only_indices=only_indices)


@app.command("ui")
def ui(
    host: str = typer.Option("0.0.0.0", "--host", help="Flask host."),
    port: int = typer.Option(5050, "--port", help="Flask port."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="YAML config path."),
):
    settings = _load_settings(config)
    app_flask = create_app(settings, config_path=config)
    app_flask.run(host=host, port=port, debug=settings.flask.debug)


def main():
    app()


if __name__ == "__main__":
    main()
