"""Small dependency-free terminal table formatter."""


def print_table(headers: list[str], rows: list[list[object]]) -> None:
    rendered = [[str(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in rendered:
        widths = [max(width, len(value)) for width, value in zip(widths, row)]
    print("  ".join(header.ljust(width) for header, width in zip(headers, widths)))
    print("  ".join("-" * width for width in widths))
    for row in rendered:
        print("  ".join(value.ljust(width) for value, width in zip(row, widths)))
