"""Untrusted contest ZIP validation; fixtures are original synthetic files."""

import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "template_import", Path(__file__).resolve().parents[1] / "tools/import_official_template.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


# ---- archive ----------------------------------------------------------------
def archive(entries):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as package:
        for name, content in entries:
            item = zipfile.ZipInfo("fixture")
            item.filename = name
            package.writestr(item, content)
    return data.getvalue()


# ---- content and path identity -----------------------------------------------
def test_template_uses_content_hashes_not_zip_metadata():
    data = b"original synthetic fixture"
    expected = {"op_kernel/example.cpp": hashlib.sha256(data).hexdigest()}
    assert module.validated_files(archive([("code/op_kernel/example.cpp", data)]), expected) == {
        "op_kernel/example.cpp": data
    }
    with pytest.raises(ValueError, match="changed"):
        module.validated_files(archive([("code/op_kernel/example.cpp", b"changed")]), expected)


@pytest.mark.parametrize("name", ["../escape", "code/../../escape", "/absolute", "code/x\\evil"])
def test_template_rejects_path_traversal(name):
    with pytest.raises(ValueError, match="Unsafe"):
        module.validated_files(archive([(name, b"fixture")]), {})


def test_template_rejects_missing_and_additional_files():
    with pytest.raises(ValueError, match="Incomplete"):
        module.validated_files(archive([]), {"required.cpp": "fixture-hash"})
    with pytest.raises(ValueError, match="Unexpected"):
        module.validated_files(archive([("code/unexpected.cpp", b"fixture")]), {})
