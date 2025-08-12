"""
Entry point for running the data registry as a module.
"""


def main():
    """Entry point for running the data registry as a module."""
    from .registry import app

    app()


if __name__ == "__main__":
    main()
