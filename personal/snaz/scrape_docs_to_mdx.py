#!/usr/bin/env python3
"""
Scrape docs.transluce.org and convert to Mintlify-compatible MDX files.

Uses BeautifulSoup for proper HTML parsing instead of regex.
"""

import re
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag


def fetch_page(url: str) -> str:
    """Fetch HTML content from URL."""
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8")


def fix_link(href: str) -> str:
    """Convert mkdocs relative links to Mintlify absolute paths."""
    if not href or href.startswith("http") or href.startswith("#"):
        return href

    # Strip all ../ and ./ prefixes
    path = re.sub(r"^(\.\./)+", "", href)
    path = re.sub(r"^\./", "", path)
    # Remove trailing slash and .md extension
    path = re.sub(r"/$", "", path)
    path = re.sub(r"\.md$", "", path)

    # Convert known paths
    if path in ["transcript", "agent_run", "chat_messages", "metadata", "llm_output"]:
        path = path.replace("_", "-")
        return f"/concepts/data-models/{path}"
    elif path == "quickstart":
        return "/quickstart"
    elif path.startswith("concepts/"):
        return f"/{path}"
    else:
        return f"/{path}"


def get_text_content(element) -> str:
    """Get text content from an element, stripping HTML tags."""
    if isinstance(element, NavigableString):
        return str(element)
    if isinstance(element, Tag):
        return element.get_text()
    return ""


def wrap_code_block(code: str, lang: str = "python") -> str:
    """Wrap code in a fenced code block, using 4 backticks if code contains triple backticks."""
    code = code.strip()
    if "```" in code:
        return f"\n````{lang}\n{code}\n````\n"
    return f"\n```{lang}\n{code}\n```\n"


def convert_code_element(element: Tag) -> str:
    """Convert a code element to markdown inline code or code block."""
    code_text = element.get_text()
    # Check if it's inside a pre (code block) or standalone (inline)
    if element.parent and element.parent.name == "pre":
        return code_text  # Will be handled by pre processing
    return f"`{code_text}`"


def convert_table(table: Tag) -> str:
    """Convert an HTML table to markdown table."""
    rows = []

    # Get headers
    thead = table.find("thead")
    if thead:
        header_cells = []
        for th in thead.find_all("th"):
            cell_text = th.get_text().strip()
            header_cells.append(cell_text)
        if header_cells:
            rows.append("| " + " | ".join(header_cells) + " |")
            rows.append("| " + " | ".join("---" for _ in header_cells) + " |")

    # Get body rows
    tbody = table.find("tbody")
    if tbody:
        for tr in tbody.find_all("tr"):
            cells = []
            for td in tr.find_all("td"):
                cell_text = convert_element(td).strip()
                # Clean up - replace newlines with spaces for table cells
                cell_text = " ".join(cell_text.split())
                cells.append(cell_text)
            if cells:
                rows.append("| " + " | ".join(cells) + " |")

    return "\n" + "\n".join(rows) + "\n" if rows else ""


def convert_element(element, depth: int = 0) -> str:
    """Recursively convert an HTML element to markdown."""
    if isinstance(element, NavigableString):
        text = str(element)
        # Don't return pure whitespace at top level
        if depth == 0 and not text.strip():
            return ""
        return text

    if not isinstance(element, Tag):
        return ""

    tag = element.name
    classes = element.get("class", [])

    # Skip navigation and non-content elements
    if any(c in classes for c in ["md-nav", "headerlink", "md-nav__list", "tabbed-labels"]):
        return ""

    # Handle specific tags
    if tag == "code":
        parent = element.parent
        # If parent is pre, this is a code block - just return text
        if parent and parent.name == "pre":
            return element.get_text()
        # Otherwise inline code
        return f"`{element.get_text()}`"

    elif tag == "pre":
        code_elem = element.find("code")
        if code_elem:
            code_text = code_elem.get_text()
            return wrap_code_block(code_text, "python")
        return wrap_code_block(element.get_text(), "")

    elif tag == "a":
        href = element.get("href", "")
        text = element.get_text().strip()
        if not text:
            return ""
        if href.startswith("#"):
            # Anchor link - just return the text with code formatting if appropriate
            return f"`{text}`"
        href = fix_link(href)
        return f"[{text}]({href})"

    elif tag in ["strong", "b"]:
        inner = "".join(convert_element(c, depth + 1) for c in element.children)
        return f"**{inner.strip()}**"

    elif tag in ["em", "i"]:
        inner = "".join(convert_element(c, depth + 1) for c in element.children)
        return f"*{inner.strip()}*"

    elif tag == "p":
        inner = "".join(convert_element(c, depth + 1) for c in element.children)
        return f"\n{inner.strip()}\n"

    elif tag == "ul":
        items = []
        for li in element.find_all("li", recursive=False):
            item_content = "".join(convert_element(c, depth + 1) for c in li.children)
            items.append(f"- {item_content.strip()}")
        return "\n" + "\n".join(items) + "\n"

    elif tag == "ol":
        items = []
        for i, li in enumerate(element.find_all("li", recursive=False), 1):
            item_content = "".join(convert_element(c, depth + 1) for c in li.children)
            items.append(f"{i}. {item_content.strip()}")
        return "\n" + "\n".join(items) + "\n"

    elif tag == "table":
        return convert_table(element)

    elif tag == "h1":
        inner = "".join(convert_element(c, depth + 1) for c in element.children)
        return f"\n# {inner.strip()}\n"

    elif tag == "h2":
        # Check for doc-heading structure (module/class definitions)
        if "doc-heading" in classes:
            name_elem = element.find(class_="doc-object-name")
            labels_elem = element.find(class_="doc-labels")

            if name_elem:
                name = name_elem.get_text().strip()
                # Skip module-level headings like "docent.data_models.agent_run"
                if name.startswith("docent."):
                    return ""
                label_parts = []
                if labels_elem:
                    for label in labels_elem.find_all("small"):
                        label_parts.append(f"`{label.get_text().strip()}`")
                label_str = " " + " ".join(label_parts) if label_parts else ""
                return f"\n## **{name}**{label_str}\n"

        inner = "".join(convert_element(c, depth + 1) for c in element.children)
        if not inner.strip():
            return ""
        return f"\n## {inner.strip()}\n"

    elif tag == "h3":
        # Check for doc-heading structure (class definitions)
        if "doc-heading" in classes:
            name_elem = element.find(class_="doc-object-name")
            labels_elem = element.find(class_="doc-labels")

            if name_elem:
                name = name_elem.get_text().strip()
                label_parts = []
                if labels_elem:
                    for label in labels_elem.find_all("small"):
                        label_parts.append(f"`{label.get_text().strip()}`")
                label_str = " " + " ".join(label_parts) if label_parts else ""
                return f"\n### **{name}**{label_str}\n"

        inner = "".join(convert_element(c, depth + 1) for c in element.children)
        if not inner.strip():
            return ""
        return f"\n### {inner.strip()}\n"

    elif tag == "h4":
        # Check for doc-heading structure (method/property definitions)
        if "doc-heading" in classes:
            name_elem = element.find(class_="doc-object-name")
            labels_elem = element.find(class_="doc-labels")

            if name_elem:
                name = name_elem.get_text().strip()
                label_parts = []
                if labels_elem:
                    for label in labels_elem.find_all("small"):
                        label_parts.append(f"`{label.get_text().strip()}`")
                label_str = " " + " ".join(label_parts) if label_parts else ""
                return f"\n#### **{name}**{label_str}\n"

        inner = "".join(convert_element(c, depth + 1) for c in element.children)
        if not inner.strip():
            return ""
        return f"\n#### {inner.strip()}\n"

    elif tag == "h5":
        inner = "".join(convert_element(c, depth + 1) for c in element.children)
        if not inner.strip():
            return ""
        return f"\n##### {inner.strip()}\n"

    elif tag == "details":
        # Collapsible section - convert to Accordion
        summary = element.find("summary")
        summary_text = summary.get_text().strip() if summary else "Details"
        # Clean up summary text
        summary_text = " ".join(summary_text.split())

        # For source code accordions, use path as title with code icon
        accordion_attrs = f'title="{summary_text}"'
        if summary_text.startswith("Source code in "):
            path = summary_text[len("Source code in ") :]
            accordion_attrs = f'title="{path}" icon="code"'

        # Get content (everything except summary)
        content_parts = []
        for child in element.children:
            if isinstance(child, Tag) and child.name != "summary":
                content_parts.append(convert_element(child, depth + 1))
            elif isinstance(child, NavigableString) and child.strip():
                content_parts.append(str(child))

        content = "".join(content_parts).strip()
        return f"\n<Accordion {accordion_attrs}>\n\n{content}\n\n</Accordion>\n"

    elif tag == "div":
        # Check for specific div types
        if "highlight" in classes:
            # Code block div
            code_elem = element.find("code")
            if code_elem:
                code_text = code_elem.get_text()
                return wrap_code_block(code_text, "python")
            pre_elem = element.find("pre")
            if pre_elem:
                return wrap_code_block(pre_elem.get_text(), "python")

        elif "doc-contents" in classes:
            # Documentation content - process all children
            return "".join(convert_element(c, depth + 1) for c in element.children)

        elif "doc-object" in classes:
            # A documented object (class, function, etc.)
            return "".join(convert_element(c, depth + 1) for c in element.children)

        elif "tabbed-content" in classes:
            # Tab content - just get the content
            return "".join(convert_element(c, depth + 1) for c in element.children)

        else:
            # Generic div - process children
            return "".join(convert_element(c, depth + 1) for c in element.children)

    elif tag == "span":
        if "doc-section-title" in classes:
            # Section title like "Attributes:", "Parameters:"
            inner = element.get_text().strip()
            return f"\n**{inner}**\n"
        elif "doc-object-name" in classes:
            # Object name - will be handled by h4 processing
            return ""
        elif "doc-labels" in classes:
            # Labels - will be handled by h4 processing
            return ""
        else:
            return "".join(convert_element(c, depth + 1) for c in element.children)

    elif tag == "br":
        return "\n"

    elif tag == "hr":
        return "\n---\n"

    elif tag == "img":
        alt = element.get("alt", "")
        src = element.get("src", "")
        if src.startswith("../"):
            src = "/" + re.sub(r"^(\.\./)+", "", src)
        return f"![{alt}]({src})"

    elif tag in ["nav", "script", "style", "button"]:
        # Skip these entirely
        return ""

    else:
        # Default: process children
        return "".join(convert_element(c, depth + 1) for c in element.children)


def parse_page(url: str, title: str) -> str:
    """Parse a mkdocs page and convert to MDX."""
    html_content = fetch_page(url)
    soup = BeautifulSoup(html_content, "html.parser")

    # Find the main article content
    article = soup.find("article")
    if not article:
        raise ValueError("Could not find article element")

    # Convert article content to markdown
    content_parts = []
    for child in article.children:
        md = convert_element(child)
        if md.strip():
            content_parts.append(md)

    content = "\n".join(content_parts)

    # Clean up excessive newlines
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = content.strip()

    # Convert LaTeX tau to unicode
    content = content.replace(r"\(\tau\)", "τ")
    content = content.replace(r"$\tau$", "τ")

    # Build MDX - only include title, no fabricated description
    mdx = f"""---
title: "{title}"
---

{content}
"""

    return mdx


# Page configurations
PAGES = [
    {
        "url": "https://docs.transluce.org/en/latest/concepts/data_models/agent_run/",
        "output": "concepts/data-models/agent-run.mdx",
        "title": "Agent Run",
    },
    {
        "url": "https://docs.transluce.org/en/latest/concepts/data_models/transcript/",
        "output": "concepts/data-models/transcript.mdx",
        "title": "Transcript",
    },
    {
        "url": "https://docs.transluce.org/en/latest/concepts/data_models/chat_messages/",
        "output": "concepts/data-models/chat-messages.mdx",
        "title": "Chat Messages",
    },
    {
        "url": "https://docs.transluce.org/en/latest/concepts/data_models/metadata/",
        "output": "concepts/data-models/metadata.mdx",
        "title": "Metadata",
    },
    {
        "url": "https://docs.transluce.org/en/latest/concepts/data_models/llm_output/",
        "output": "concepts/data-models/llm-output.mdx",
        "title": "LLM Output",
    },
]


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Scrape docs.transluce.org to MDX")
    parser.add_argument("--output-dir", default="mint-docs", help="Output directory for MDX files")
    parser.add_argument("--page", help="Only process a specific page (by output path)")
    parser.add_argument("--dry-run", action="store_true", help="Print output instead of writing files")

    args = parser.parse_args()
    output_dir = Path(args.output_dir)

    for page in PAGES:
        if args.page and page["output"] != args.page:
            continue

        print(f"Processing: {page['url']}")

        try:
            mdx_content = parse_page(page["url"], page["title"])

            if args.dry_run:
                print(f"\n{'=' * 60}")
                print(f"Would write to: {output_dir / page['output']}")
                print("=" * 60)
                print(mdx_content[:4000])
                if len(mdx_content) > 4000:
                    print(f"\n... ({len(mdx_content) - 4000} more characters)")
            else:
                output_path = output_dir / page["output"]
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(mdx_content)
                print(f"  -> Wrote: {output_path}")

        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    main()
