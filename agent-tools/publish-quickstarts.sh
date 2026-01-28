# Assemble cursor quickstart
mkdir -p cursor-quickstart/.cursor/rules
cp ./SKILL.md cursor-quickstart/.cursor/rules/docent.mdc
zip -r ./cursor-quickstart.zip cursor-quickstart/.cursor cursor-quickstart/docent.env cursor-quickstart/pyproject.toml

# Assemble vscode quickstart
mkdir -p vscode-quickstart/.vscode
cp ./SKILL.md vscode-quickstart/AGENTS.md
cp cursor-quickstart/docent.env vscode-quickstart/docent.env
cp cursor-quickstart/pyproject.toml vscode-quickstart/pyproject.toml
jq '.servers = .mcpServers | del(.mcpServers)' \
  cursor-quickstart/.cursor/mcp.json > vscode-quickstart/.vscode/mcp.json
zip -r ./vscode-quickstart.zip vscode-quickstart/.vscode vscode-quickstart/AGENTS.md vscode-quickstart/docent.env vscode-quickstart/pyproject.toml

# Publish both quickstarts + standalone rules file
aws s3 cp ./vscode-quickstart.zip s3://docent-public-assets/vscode-quickstart.zip
aws s3 cp ./cursor-quickstart.zip s3://docent-public-assets/cursor-quickstart.zip
aws s3 cp ./SKILL.md s3://docent-public-assets/docent.mdc
