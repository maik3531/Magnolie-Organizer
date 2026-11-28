from pathlib import Path
import sys, hashlib
source = Path(sys.argv[1]).read_text()
start = source.index("    fun fetch(")
end = source.index("    companion object {", start)
method = source[start:end]
digest = hashlib.sha256(method.encode()).hexdigest()
assert digest in ("0c3bae0f01236eb219c85d3b87c7ba8ec891e7e20d0ffe804dfff7d7d76fd649", "4bc273487707a42295d0a191e938ef16b3c5143ff3573b66f4bcb4fdeaec9b9a"), digest
template = Path(__file__).with_name("Host.template.kt").read_text()
Path(sys.argv[2]).write_text(template.replace("// INSERT EXACT FETCH METHOD HERE\n\n", method))
print(digest)
