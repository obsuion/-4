from pathlib import Path


def test_readme_describes_completed_optional_geometry_contacts():
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    lowered = readme.lower()

    assert "## V2.4 Final" in readme
    assert "--contact-model geometry" in readme
    assert "position_at_time(7.5)" in readme
    assert "no geometry-based contacts" not in lowered
    assert "geometry-based contacts are absent" not in lowered
