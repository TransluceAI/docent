## Development

If you update any python packages, you'll need to update the `requirements-locked.txt` file.

From /docent-platform, run:

```
uv export --extra dev --no-editable --no-hashes --format requirements-txt > docs/requirements-locked.txt`
```

Make sure not to clear `index.md` or README.md [will become the home page](https://www.mkdocs.org/user-guide/writing-your-docs/#index-pages).
