import pathlib


def find_monorepo_root() -> pathlib.Path:
    """Find the monorepo root by looking for 'lib' and 'project' directories."""
    current = pathlib.Path(__file__).resolve().parent.parent.parent.parent

    if not (current / "lib").is_dir() or not (current / "project").is_dir():
        raise RuntimeError("Error: Could not find monorepo root.")

    return current


def get_package_path(package_name: str) -> pathlib.Path:
    """Get the path to a package in either project/, lib/, or personal/.

    Args:
        package_name: Name of the package to find. If starts with "personal_",
                     looks in personal/{name} instead.

    Returns:
        Path to the package directory

    Raises:
        typer.Exit: If package is not found
    """
    monorepo_root = find_monorepo_root()

    # Check for personal directory
    if package_name.startswith("personal_"):
        personal_name = package_name.removeprefix("personal_")
        personal_path = monorepo_root / "personal" / personal_name
        if personal_path.is_dir():
            return personal_path
        raise RuntimeError(f"Error: Personal directory '{personal_name}' not found in personal/")

    # Try project/ and lib/ directories
    project_path = monorepo_root / "project" / package_name
    lib_path = monorepo_root / "lib" / package_name
    # external_path = monorepo_root / "external" / package_name

    if project_path.is_dir():
        return project_path
    elif lib_path.is_dir():
        return lib_path
    # elif external_path.is_dir():
    #     return external_path
    else:
        raise RuntimeError(
            f"Error: Package '{package_name}' not found in project/, lib/, or external/ directories."
        )


def has_pyproject_toml(directory: pathlib.Path) -> bool:
    """Check if a directory contains a pyproject.toml file.

    Args:
        directory: Directory to check

    Returns:
        bool: True if pyproject.toml exists in the directory
    """
    return (directory / "pyproject.toml").is_file()
