"""Infer business processes from screen flows."""

from __future__ import annotations

from code_analysis.models import ProcessNode, Rel, ScreenNode


def build_processes(screens: list[ScreenNode]) -> tuple[list[ProcessNode], list[Rel], list[Rel]]:
    """Create one inferred process per business module from its screens."""
    processes: list[ProcessNode] = []
    has_process: list[Rel] = []
    has_step: list[Rel] = []

    screens_by_module: dict[str, list[ScreenNode]] = {}
    for screen in screens:
        screens_by_module.setdefault(screen.module, []).append(screen)

    for module, module_screens in sorted(screens_by_module.items()):
        if not module_screens:
            continue

        ordered = sorted(module_screens, key=lambda screen: screen.view_path)
        process_id = f"process:{module}:main"
        process_name = f"{module}:main"
        business_id = f"business:{module}"

        processes.append(
            ProcessNode(
                id=process_id,
                name=process_name,
                module=module,
                step_order=[screen.view_path for screen in ordered],
            )
        )
        has_process.append(Rel(from_id=business_id, to_id=process_id))
        for screen in ordered:
            has_step.append(Rel(from_id=process_id, to_id=screen.id))

    return processes, has_process, has_step
