"""Exercise the actual response-file writer expression without running MSVC."""
import ast
from pathlib import Path
import runpy

import pytest


TOOLS = Path(__file__).resolve().parents[1] / 'werkzeuge'


@pytest.mark.parametrize('filename', ('phone_audio_parent.py', 'phone_audio_runtime.py', 'phone_camera_source.py'))
def test_linker_tail_stays_on_the_link_line_and_source_quotes_survive(filename):
    path = TOOLS / filename
    tree = ast.parse(path.read_text())
    build = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'build')
    writer, = [node for node in ast.walk(build) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr == 'write_text'
               and '.rsp' in ast.unparse(node.func.value)]
    arguments = ['/nologo', '/std:c++17', '"C:\\path with spaces\\source.cpp"', '/link', '/WX',
                 '/DYNAMICBASE', '/NXCOMPAT', '/guard:cf', '/MACHINE:X64',
                 '/DEF:"C:\\path with spaces\\source.def"', 'mfplat.lib']
    namespace = runpy.run_path(str(path)); namespace['arguments'] = arguments
    result = eval(compile(ast.Expression(writer.args[0]), str(path), 'eval'), namespace)
    assert result.splitlines() == arguments[:3] + [' '.join(arguments[3:])], (
        'cl.exe routes only the same response-file line after /link to the linker')
    assert result.endswith('\n')


@pytest.mark.parametrize('filename', ('phone_audio_parent.py', 'phone_audio_runtime.py', 'phone_camera_source.py'))
@pytest.mark.parametrize('arguments', (['/nologo'], ['/link', '/link']))
def test_invalid_linker_delimiters_are_not_silently_written(filename, arguments):
    namespace = runpy.run_path(str(TOOLS / filename))
    with pytest.raises(ValueError, match='Exactly one linker delimiter'):
        namespace['_response_file_text'](arguments)
