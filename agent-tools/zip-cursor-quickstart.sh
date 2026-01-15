#!/bin/bash

mkdir -p cursor-quickstart/.cursor/rules
cp ./SKILL.md cursor-quickstart/.cursor/rules/docent.mdc
zip -r ../mint-docs/assets/cursor-quickstart.zip cursor-quickstart/.cursor cursor-quickstart/docent.env cursor-quickstart/pyproject.toml
rm cursor-quickstart/.cursor/rules/docent.mdc
