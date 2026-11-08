// Read-only queries against the labelled Olden Era program. Targets are absolute VAs (0x18...) or symbol names
// (NativeType$$native or InteropType$$Member, exact match; a trailing * matches a prefix).
// Args: <out.txt> <cmd> <target>... where cmd is
//   decomp   decompiled C of each target function
//   callers  functions that reference each target (from disassembly; no auto-analysis, so indirect calls
//            and vtable dispatch are missing)
//   callees  functions each target calls
//   find     list symbols matching each target
//@category OldenEra
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;

import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

public class OeQuery extends GhidraScript {
    private PrintWriter out;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 3) throw new IllegalArgumentException("usage: OeQuery <out.txt> <decomp|callers|callees|find> <target>...");
        out = new PrintWriter(new FileWriter(args[0], true));
        String cmd = args[1];
        DecompInterface d = null;
        if (cmd.equals("decomp")) {
            d = new DecompInterface();
            d.setOptions(new DecompileOptions());
            d.openProgram(currentProgram);
        }
        for (int i = 2; i < args.length; i++) {
            String t = args[i];
            out.println("// ===== " + cmd + " " + t);
            if (cmd.equals("find")) { listSymbols(t); continue; }
            List<Function> fs = resolve(t);
            if (fs.isEmpty()) { out.println("// no function for " + t); continue; }
            for (Function f : fs) {
                out.println("// " + f.getName() + " @ " + f.getEntryPoint() + names(f.getEntryPoint()));
                switch (cmd) {
                    case "decomp": {
                        DecompileResults r = d.decompileFunction(f, 180, monitor);
                        out.println(r.getDecompiledFunction() != null ? r.getDecompiledFunction().getC() : "// failed: " + r.getErrorMessage());
                        break;
                    }
                    case "callers": {
                        Set<String> seen = new LinkedHashSet<>();
                        for (Reference ref : getReferencesTo(f.getEntryPoint())) {
                            Function c = getFunctionContaining(ref.getFromAddress());
                            seen.add(ref.getReferenceType() + " " + ref.getFromAddress() + " in " + (c == null ? "?" : c.getName() + " @ " + c.getEntryPoint()));
                        }
                        for (String s : seen) out.println(s);
                        out.println("// " + seen.size() + " references");
                        break;
                    }
                    case "callees": {
                        for (Function c : f.getCalledFunctions(monitor)) out.println(c.getEntryPoint() + " " + c.getName());
                        break;
                    }
                    default: throw new IllegalArgumentException("unknown command " + cmd);
                }
            }
            out.flush();
        }
        out.println("// OeQuery done");
        out.close();
    }

    private String names(Address a) {
        StringBuilder b = new StringBuilder();
        for (Symbol s : currentProgram.getSymbolTable().getSymbols(a))
            if (!s.isPrimary()) b.append(" aka ").append(s.getName());
        String plate = getPlateComment(a);
        if (plate != null) b.append("\n// ").append(plate.replace("\n", " "));
        return b.toString();
    }

    private List<Function> resolve(String t) {
        List<Function> fs = new ArrayList<>();
        if (t.startsWith("0x") || t.startsWith("0X")) {
            Address a = toAddr(Long.parseUnsignedLong(t.substring(2), 16));
            Function f = getFunctionContaining(a);
            if (f != null) fs.add(f);
            return fs;
        }
        Set<Address> seen = new LinkedHashSet<>();
        SymbolIterator it = currentProgram.getSymbolTable().getSymbolIterator(t, true);
        while (it.hasNext()) {
            Symbol s = it.next();
            Function f = getFunctionAt(s.getAddress());
            if (f != null && seen.add(f.getEntryPoint())) fs.add(f);
            if (fs.size() >= 50) break;
        }
        return fs;
    }

    private void listSymbols(String t) {
        int n = 0;
        SymbolIterator it = currentProgram.getSymbolTable().getSymbolIterator(t, true);
        while (it.hasNext() && n < 500) {
            Symbol s = it.next();
            out.println(s.getAddress() + " " + s.getName() + (s.isPrimary() ? "" : " (alias)"));
            n++;
        }
        out.println("// " + n + " symbols" + (n >= 500 ? " (capped)" : ""));
    }
}
