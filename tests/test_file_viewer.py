import file_viewer


def test_markdown_and_physical_path(tmp_path):
    doc = tmp_path / "con espacios.md"
    doc.write_text("# Título", encoding="utf-8")
    code, data = file_viewer.read_file(str(doc), [str(tmp_path)])
    assert code == 200
    assert data == {"path": str(doc.resolve()), "text": "# Título", "markdown": True}


def test_rejects_escape_and_binary(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "privado.md"
    outside.write_text("privado", encoding="utf-8")
    assert file_viewer.read_file(str(root / ".." / outside.name), [str(root)])[0] == 403
    binary = root / "archivo.bin"
    binary.write_bytes(b"a\x00b")
    assert file_viewer.read_file(str(binary), [str(root)])[0] == 415


def test_missing_and_large(tmp_path):
    assert file_viewer.read_file(str(tmp_path / "no.md"), [str(tmp_path)])[0] == 404
    large = tmp_path / "grande.txt"
    large.write_bytes(b"a" * (file_viewer.MAX_BYTES + 1))
    assert file_viewer.read_file(str(large), [str(tmp_path)])[0] == 413
