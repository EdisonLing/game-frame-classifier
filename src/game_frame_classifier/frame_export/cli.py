"""Frame Export Kit command line: prompts, scan summary, run and finish (Frame Export Kit spec §2)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from game_frame_classifier.sourcing import ffbin, gpu
from game_frame_classifier.sourcing.labels import (
    DISPLAY_NAMES,
    OTHER,
    label_hints,
    normalize_handle,
    normalize_other_name,
)
from game_frame_classifier.sourcing.recipe import Recipe, RecipeError, load_recipe
from game_frame_classifier.sourcing.timeinfo import local_day

from . import __version__, paths, settings
from .run import (
    DISK_FACTOR,
    DiskSpaceError,
    RunContext,
    RunLog,
    estimate_bytes,
    estimate_seconds,
    finalize,
    fmt_bytes,
    fmt_duration,
    load_state,
    new_state,
    process,
    save_state,
    work_dir,
)
from .scan import ScanItem, apply_budget, discover, fingerprint, probe_all

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_DISK = 3
EXIT_INTERRUPTED = 130

REASONS = {
    "not_video": "not a video",
    "steam_recording": "Steam recording: export the clip to MP4 in Steam first",
    "path_too_long": "path too long: move the folder closer to the drive root",
    "unreadable": "could not be read",
    "no_video": "no video stream",
    "too_short": "too short",
}

NOTICE = """\
This tool turns your game clips into still pictures for a school machine-learning project.

What it saves: one picture every {interval} seconds from each clip (plus a lower-quality
copy of the same picture, unless you pick quick mode), the clip file names, recording
dates and basic video info (resolution, length, frame rate). It also notes your Windows
version, number of CPU cores, graphics card model and time zone, to explain differences
between packs. No audio and no video. Nothing is uploaded: you send the zip yourself.
Your clips are only read, never changed.

The data stays on my PC for this project. Ask me any time and I will delete it.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gfc-frame-export", description="Turn a folder of game clips into a frames zip.")
    p.add_argument("folder", nargs="?", help="folder with clips (one game per folder)")
    p.add_argument("--game", help="game label, for example Valorant, or Other")
    p.add_argument("--other-name", help="game name when using --game Other")
    p.add_argument("--compact", action="store_true", help="save 256x144 pictures instead of native size")
    p.add_argument("--budget-hours", type=float, help="hours of footage to process this run (0 = all)")
    p.add_argument("--yes", action="store_true", help="no prompts; use defaults")
    p.add_argument("--include-packed", action="store_true", help="also process clips sent in an earlier run")
    p.add_argument("--no-zip", action="store_true", help="leave the pack folder unzipped")
    p.add_argument("--output", help="existing folder to save the finished zip in (default: the tool's output folder)")
    p.add_argument("--no-open", action="store_true", help="do not open Explorer when done")
    p.add_argument("--cpu", action="store_true", help="decode and encode on the CPU even if the graphics card works")
    p.add_argument("--change-mode", action="store_true", help="choose again between quick mode and both qualities")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{prompt}{suffix}: ").strip() or default


def ask_yes_no(prompt: str, default: bool | None) -> bool:
    hint = {True: "Y/n", False: "y/N", None: "y/n"}[default]
    while True:
        answer = input(f"{prompt} [{hint}]: ").strip().lower()
        if not answer and default is not None:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please type y or n.")


QUICK_NOTE = """
Quality mode. By default the tool saves each picture twice: once at full quality,
and once from a deliberately low-quality copy of the video, which is most of the work.
The low-quality copy teaches the model to handle blurry, stream-like video, and it can
only be made from your original videos, not from the pictures afterwards.
Quick mode skips it: about 4 times faster, but your pictures are less useful (they
still help the rest of the training). If you have the time, please keep both.
You can change this later: at the Start question, type m.
"""


def ask_quality_mode() -> str:
    print(QUICK_NOTE)
    return "quick" if ask_yes_no("Use quick mode (faster, but less useful pictures)?", False) else "both"


def mode_label(mode: str) -> str:
    return "quick (full quality only)" if mode == "quick" else "both qualities (full and low)"


def mode_overrides(mode: str) -> dict[str, Any]:
    return {"crf_list": []} if mode == "quick" else {}


def ask_start() -> str:
    """"yes", "no" or "mode" (change the quality mode first)."""
    while True:
        answer = input("Start? [Y/n, or m to change the quality mode]: ").strip().lower()
        if answer in ("", "y", "yes"):
            return "yes"
        if answer in ("n", "no"):
            return "no"
        if answer in ("m", "mode"):
            return "mode"
        print("Please type y, n or m.")


def first_run(recipe: Recipe) -> settings.UserSettings | None:
    print(NOTICE.format(interval=f"{recipe.interval_s:g}"))
    handle = ""
    while not handle:
        handle = normalize_handle(input("Your name or nickname: "))
        if not handle:
            print("Please use at least one letter or number.")
    if not ask_yes_no("OK to process your clips into pictures for this project?", True):
        print("OK. Nothing was processed and nothing was saved.")
        return None
    public = ask_yes_no("OK if a few of your pictures appear in my report or README?", True)
    user = settings.new_user(handle, public)
    user.quality_mode = ask_quality_mode()
    settings.save_user(user)
    print(f"Saved. You are '{handle}'.\n")
    return user


def ask_folder() -> Path | None:
    while True:
        raw = input("Drag the folder with your clips into this window, then press Enter:\n> ").strip().strip('"').strip()
        if not raw:
            return None
        path = Path(raw)
        if path.is_dir():
            return path
        print("That is not a folder. Try again, or press Enter to quit.")


def resolve_game(text: str, options: list[str]) -> str | None:
    key = text.strip().lower()
    for game in options:
        if key in (game.lower(), DISPLAY_NAMES.get(game, game).lower()):
            return game
    return None


def prompt_game(options: list[str], default: str | None, suggestion: str | None) -> str:
    note = f"  (names suggest: {DISPLAY_NAMES.get(suggestion, suggestion)})" if suggestion else ""
    print(f"\nWhich game are these clips from?{note}")
    for k, game in enumerate(options, 1):
        print(f"  {k} {DISPLAY_NAMES.get(game, game.replace('_', ' '))}")
    default_num = str(options.index(default) + 1) if default in options else ""
    while True:
        answer = ask("Type a number", default_num)
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        game = resolve_game(answer, options)
        if game:
            return game
        print(f"Please type a number from 1 to {len(options)}.")


def choose_game(
    args: argparse.Namespace,
    interactive: bool,
    options: list[str],
    hints: set[str],
    user: settings.UserSettings,
) -> str | None:
    suggestion = next(iter(hints)) if len(hints) == 1 else None
    if args.game:
        game = resolve_game(args.game, options)
        if game is None:
            print(f"Unknown game: {args.game}. Use one of: {', '.join(options)}")
            return None
    elif not interactive:
        if suggestion is None:
            print("Add --game: the file and folder names don't show which game this is.")
            return None
        game = suggestion
    else:
        default = suggestion or (user.last_game if user.last_game in options else None)
        while True:
            game = prompt_game(options, default, suggestion)
            if not hints or game in hints:
                return game
            names = ", ".join(DISPLAY_NAMES.get(h, h) for h in sorted(hints))
            if ask_yes_no(f"The file and folder names suggest {names}. Use {DISPLAY_NAMES.get(game, game)} anyway?", False):
                return game
    if hints and game not in hints:
        print(f"Warning: the file and folder names suggest {', '.join(sorted(hints))}.")
    return game


def ask_notes(recipe: Recipe, game: str, interactive: bool) -> dict[str, Any]:
    notes: dict[str, Any] = {}
    game_specific: dict[str, str] = {}
    questions = [(q, False) for q in recipe.questions.get("all", [])]
    questions += [(q, True) for q in recipe.questions.get(game, [])]
    if interactive and questions:
        print("\nOptional questions (press Enter to skip):")
    for q, specific in questions:
        answer = q["default"]
        if interactive:
            choices = [str(c) for c in q["choices"]]
            while True:
                raw = input(f"  {q['prompt']} ({'/'.join(choices)}) [{q['default']}]: ").strip().lower()
                if not raw:
                    break
                match = next((c for c in choices if c.lower() == raw), None)
                if match:
                    answer = match
                    break
                print(f"  Please type one of: {', '.join(choices)}")
        (game_specific if specific else notes)[q["key"]] = answer
    notes["game_specific"] = game_specific
    notes["free_text"] = input("  Anything else I should know? (Enter to skip): ").strip()[:500] if interactive else ""
    return notes


def print_summary(items: list[ScanItem]) -> None:
    videos = [it for it in items if it.info is not None]
    total = sum(it.info.duration_s for it in videos)
    sizes = Counter(f"{it.info.width}x{it.info.height}" for it in videos)
    resolution = ""
    if sizes:
        resolution = ", " + sizes.most_common(1)[0][0] + (" and others" if len(sizes) > 1 else "")
    print(f"Found {len(videos)} new videos ({fmt_duration(total)}{resolution}).")
    listed = [it for it in items if it.status == "skipped" and it.detail in REASONS]
    if listed:
        shown = "; ".join(f"{it.relpath} ({REASONS[it.detail]})" for it in listed[:5])
        more = f"; and {len(listed) - 5} more" if len(listed) > 5 else ""
        print(f"Skipped {len(listed)}: {shown}{more}.")
    sent = sum(1 for it in items if it.detail == "already_packed")
    dups = sum(1 for it in items if it.detail == "duplicate_in_run")
    if sent:
        print(f"Already sent before (skipped): {sent}.")
    if dups:
        print(f"Duplicate copies (skipped): {dups}.")


def print_selection(items: list[ScanItem], over_budget: bool) -> None:
    if not over_budget:
        return
    chosen = [it for it in items if it.status == "selected"]
    days = len({local_day(it.times.start) for it in chosen})
    print(f"This run will process {fmt_duration(sum(it.info.duration_s for it in chosen))}: {len(chosen)} clips across {days} days.")
    print("Run it again later on the same folder to send more.")


def ask_budget(current_min: int) -> int:
    while True:
        raw = input("Press Enter to continue, or type the hours to process this time (0 = all): ").strip()
        if not raw:
            return current_min
        try:
            hours = float(raw.replace(",", "."))
        except ValueError:
            print("Please type a number of hours, like 2 or 4.5.")
            continue
        if hours < 0:
            print("Please type 0 or more.")
            continue
        return int(round(hours * 60))


def _counter(label: str):
    def show(n: int, total: int) -> None:
        print(f"\r{label}: {n}/{total}      ", end="", flush=True)
    return show


def open_explorer(path: Path) -> None:
    if os.name != "nt":
        return
    explorer = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe"
    if explorer.is_file():
        subprocess.Popen(f'"{explorer}" /select,"{path}"')


def choose_encoder(
    args: argparse.Namespace, recipe: Recipe, tools: ffbin.FFTools, probe_dir: Path,
) -> gpu.GpuStatus | None:
    """Self-test the GPU encoder and say which encoder this run uses; None means CPU by choice."""
    if args.cpu:
        print("Video encoding: CPU (--cpu).")
        return None
    if not recipe.crf_list:
        print("Video encoding: none needed (quick mode).")
        return None
    if recipe.encoder != "auto":
        print("Video encoding: CPU (set in config/recipe.json).")
        return None
    status = gpu.detect_gpu(tools, paths.ensure_inside_home(probe_dir))
    if status.available:
        print(f"Video encoding: graphics card ({status.adapter or 'Direct3D 12'}).")
    else:
        print("WARNING: The graphics card video encoder can't be used on this PC, so this run uses")
        print("         the CPU instead. The pictures are still fine to send, but it is slower and")
        print("         keeps your PC busier while it runs.")
        print(f"         Reason: {status.reason or 'unknown'}")
    return status


def print_encoder_note(ctx: RunContext, done: dict[str, dict[str, Any]]) -> None:
    """Repeat any CPU fallback at the end, where people look."""
    if ctx.gpu is None:
        return
    if not ctx.gpu.available:
        print("WARNING: This run used the CPU because the graphics card encoder wasn't available.")
        return
    cpu = sum(1 for d in done.values() if d["result"].get("low_encoder") not in (gpu.GPU_ENCODER, ""))
    if cpu:
        print(
            f"WARNING: {cpu} of {len(done)} clips were encoded on the CPU because the graphics card "
            "encoder failed. Details are in run_log.txt inside the zip."
        )


def _main(args: argparse.Namespace) -> int:
    home = paths.app_home().resolve()
    if "%" in str(home):
        print("Move this tool's folder to a path without a % sign in it, then run it again.")
        return EXIT_USAGE
    if args.budget_hours is not None and args.budget_hours < 0:
        print("--budget-hours must be 0 or more.")
        return EXIT_USAGE
    chosen_zip_dir: Path | None = None
    if args.output:
        if args.no_zip:
            print("--output and --no-zip can't be used together.")
            return EXIT_USAGE
        chosen_zip_dir = Path(args.output).resolve()
        if not chosen_zip_dir.is_dir():
            print(f"--output must be a folder that already exists: {chosen_zip_dir}")
            return EXIT_USAGE
    recipe_path = paths.config_dir() / "recipe.json"
    try:
        base = load_recipe(recipe_path)
    except RecipeError as exc:
        print(f"Problem in config/recipe.json: {exc}")
        return EXIT_USAGE
    try:
        tools = ffbin.find_tools(bundled_only=(ffbin.pack_root() / "runtime").is_dir())
    except ffbin.FFmpegNotFoundError:
        print("ffmpeg is missing. Extract the whole zip again and run START HERE.bat from the extracted folder.")
        return EXIT_USAGE
    ffbin.set_low_priority(True)
    interactive = not args.yes

    user = settings.load_user()
    if user is None:
        if not interactive:
            print("Run it once without --yes to enter your name.")
            return EXIT_USAGE
        user = first_run(base)
        if user is None:
            return EXIT_OK
    if args.change_mode and not interactive:
        print("--change-mode asks a question, so it can't be used with --yes.")
        return EXIT_USAGE
    if interactive and (user.quality_mode is None or args.change_mode):
        user.quality_mode = ask_quality_mode()
        settings.save_user(user)
        print(f"Saved: {mode_label(user.quality_mode)}.\n")
    mode = user.quality_mode or "both"

    root = Path(args.folder) if args.folder else (ask_folder() if interactive else None)
    if root is None:
        print("No folder given.")
        return EXIT_USAGE
    if not root.is_dir():
        print(f"Not a folder: {root}")
        return EXIT_USAGE
    root = root.resolve()
    if root == home or root.is_relative_to(home):
        print("That is the tool's own folder. Pick the folder that has your clips.")
        return EXIT_USAGE

    frame_mode = "compact" if args.compact else (user.frame_mode_override or base.frame_mode)
    budget_min = base.footage_budget_min if args.budget_hours is None else int(round(args.budget_hours * 60))
    recipe = load_recipe(
        recipe_path, {"frame_mode": frame_mode, "footage_budget_min": budget_min, **mode_overrides(mode)},
    )

    print(f"Scanning {root.name} ...")
    items = discover(root, recipe, exclude=home)
    fingerprint(items, settings.load_history(), args.include_packed, _counter("Reading files"))
    probe_all(items, tools, recipe, root.name, _counter("Checking videos"))
    print()
    print_summary(items)

    options = [*recipe.games, OTHER]
    hints = label_hints(root.name)
    for it in items:
        if it.info is not None:
            hints |= label_hints(f"{root.name}/{it.relpath}")
    hints &= set(recipe.games)
    game = choose_game(args, interactive, options, hints, user)
    if game is None:
        return EXIT_USAGE
    other_name = ""
    if game == OTHER:
        other_name = normalize_other_name(args.other_name or "")
        while interactive and not other_name:
            other_name = normalize_other_name(input("Game name: "))
        if not other_name:
            print("Add --other-name when using --game Other.")
            return EXIT_USAGE

    conflicts = [it for it in items if it.status == "eligible" and it.packed_game and it.packed_game != game]
    if conflicts:
        print(f"{len(conflicts)} of these clips were sent before as a different game.")
        if interactive and not ask_yes_no("Include them anyway?", False):
            for it in conflicts:
                it.skip("already_packed")

    apply_budget(items, budget_min * 60)
    over_budget = any(it.detail == "over_budget" for it in items)
    print_selection(items, over_budget)
    if over_budget and interactive and args.budget_hours is None:
        new_min = ask_budget(budget_min)
        if new_min != budget_min:
            budget_min = new_min
            recipe = load_recipe(
                recipe_path, {"frame_mode": frame_mode, "footage_budget_min": budget_min, **mode_overrides(mode)},
            )
            apply_budget(items, budget_min * 60)
            over_budget = any(it.detail == "over_budget" for it in items)
            print_selection(items, over_budget)
    selected = [it for it in items if it.status == "selected"]
    if not selected:
        print("Nothing new to process in this folder.")
        return EXIT_OK

    ctx = RunContext(root, items, recipe, tools, user, game, other_name)
    work = work_dir(ctx)
    ctx.gpu = choose_encoder(args, recipe, tools, work.parent / f"gpu_probe_{work.name}")
    ctx.decode = None if args.cpu else gpu.DecodeCheck()
    state = load_state(work)
    if state is not None:
        print("Continuing an earlier run on this folder.")
    else:
        state = new_state(ask_notes(recipe, game, interactive))

    est = estimate_bytes(selected, recipe)
    secs = estimate_seconds(selected, recipe, gpu=ctx.use_gpu)
    out_dir = paths.ensure_inside_home(paths.output_dir())
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_dir = chosen_zip_dir or out_dir
    free = shutil.disk_usage(out_dir).free
    print(f"\nThis run: {len(selected)} clips, {fmt_duration(sum(it.info.duration_s for it in selected))} of footage.")
    print(
        f"Estimated time: about {fmt_duration(secs)} to {fmt_duration(secs * 2)}. "
        f"Estimated output: about {fmt_bytes(est)}. Free space: {fmt_bytes(free)}."
    )
    print(f"Quality mode: {mode_label(mode)}.")
    if zip_dir != out_dir:
        print(f"The finished zip will be saved in: {zip_dir}")
    if free < est * DISK_FACTOR:
        print(f"Not enough free disk space: this needs about {fmt_bytes(est * DISK_FACTOR)} free on this drive.")
        return EXIT_DISK
    if zip_dir != out_dir and shutil.disk_usage(zip_dir).free < est:
        print(f"Not enough free disk space in {zip_dir}: the zip needs about {fmt_bytes(est)}.")
        return EXIT_DISK
    if interactive:
        answer = ask_start()
        if answer == "mode":
            user.quality_mode = ask_quality_mode()
            settings.save_user(user)
            print(f"Saved: {mode_label(user.quality_mode)}.\n")
            args.change_mode = False
            return _main(args)
        if answer == "no":
            print("OK, nothing was processed.")
            return EXIT_OK

    user.last_game = game
    settings.save_user(user)
    save_state(work, state)
    log = RunLog(work / "run_log.txt", root)
    log.write(
        f"run start v{__version__} game={game} recipe={recipe.recipe_id} mode={recipe.frame_mode} "
        f"clips={len(selected)} ffmpeg={tools.origin}"
    )
    if ctx.gpu is None:
        log.write("encoder cpu (chosen)")
    elif ctx.gpu.available:
        log.write(f"encoder gpu {gpu.GPU_ENCODER} adapter={ctx.gpu.adapter}")
    else:
        log.write(f"encoder cpu (gpu unavailable: {ctx.gpu.reason}) adapter={ctx.gpu.adapter}")
    print("Your PC stays usable, but the fans may spin up. You can close this window any time;")
    print("run it again on the same folder to continue where it left off.\n")
    try:
        done, failed = process(ctx, work, state, log)
    except DiskSpaceError as exc:
        print(f"\n{exc}\nFree up some space, then run it again on the same folder to continue.")
        return EXIT_DISK
    if not done:
        print(f"\nNo clips could be processed. Send me this file: {work.relative_to(home) / 'run_log.txt'}")
        return EXIT_FAIL
    result = finalize(ctx, work, state, done, failed, log, budget_min, make_zip=not args.no_zip, zip_dir=zip_dir)
    skipped = sum(1 for it in items if it.status == "skipped")
    print(f"\nDone. {len(done)} clips OK, {len(failed)} failed, {skipped} skipped.")
    print_encoder_note(ctx, done)
    if args.no_zip:
        print(f"Pack folder (not zipped): {result}")
        return EXIT_OK
    shown = result.relative_to(home) if result.is_relative_to(home) else result
    print(f"Send this file: {shown}  ({fmt_bytes(result.stat().st_size)})")
    print("Discord's free limit is 10 MB, so upload it to Google Drive, OneDrive or WeTransfer and send me the link.")
    if over_budget:
        print("Some clips were left for next time. Run it again on the same folder to send more.")
    if not args.no_open:
        open_explorer(result)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"GFC Frame Export Kit v{__version__}")
    try:
        return _main(args)
    except KeyboardInterrupt:
        print("\nStopped. Run it again on the same folder to continue where it left off.")
        return EXIT_INTERRUPTED
    except EOFError:
        print("\nNo input. Stopped.")
        return EXIT_USAGE
