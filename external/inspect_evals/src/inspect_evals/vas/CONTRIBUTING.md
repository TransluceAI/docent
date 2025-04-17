# Contributing

## Dependencies

Development dependencies are listed in [`pyproject.toml`](./pyproject.toml).
To install all dependencies for development, run:

```shell
pip install -e .[dev]
```

Dependencies for the evaluation image are defined in [`pyproject.toml`](pyproject.toml).

The project uses [`pip-tools`](https://github.com/jazzband/pip-tools) to manage dependencies.

### Tooling

The project includes some non-exhaustive type hinting, which is checked through GitHub actions. It is there to help, not
hinder so if it highlights something being wrong, it's likely a potential source of buggy behaviours. You can run it at
any time using `pyright -p src/`. It also includes `isort` and `black` to autoformat your code. You can run these at
any time using `isort src` and `black src`.

Black, isort, and pyright are checked on the CI pipeline but will not block a merge.

### Pre-commit

This repository has a [.pre-commit-config.yaml](./.pre-commit-config.yaml) file for assisting with local development.

You can install the command-line tool by going [here](https://pre-commit.com/#install).

### VSCode

If you're using VSCode, you can use extensions to automate the process (which should show up as recommended):

- <https://marketplace.visualstudio.com/items?itemName=ms-python.isort>
- <https://marketplace.visualstudio.com/items?itemName=ms-python.black-formatter>
- <https://marketplace.visualstudio.com/items?itemName=ms-python.vscode-pylance> (includes pyright)

The `.vscode` folder contains a sample settings file. Run `cp .vscode/settings.json.sample .vscode/settings.json` to use
the settings. Modify [.vscode/settings.json](./.vscode/settings.json) according to the comments to get autoformatting on
save.

## Project structure

The interfaces with the challenge projects can be found in [api](src/api).
The components of the Inspect task (task definition, dataset construction, solvers) are separated into respective 
directories.

