// Labels an Olden Era GameAssembly.dll from make_labels.py output: creates a function at every IL2CPP method
// entry (named NativeType$$native, interop name as a secondary label, signature in the plate comment) and labels
// the decoded metadata-usage globals. Refuses a program whose sha256 differs from the label file's pin.
// Args: <labels.tsv>
//@category OldenEra
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.SymbolTable;

import java.io.BufferedReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

public class ImportOeSymbols extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) throw new IllegalArgumentException("usage: ImportOeSymbols <labels.tsv>");
        List<String[]> funcs = new ArrayList<>();
        List<String[]> data = new ArrayList<>();
        String pin = null;
        try (BufferedReader r = Files.newBufferedReader(Paths.get(args[0]), StandardCharsets.UTF_8)) {
            String line;
            while ((line = r.readLine()) != null) {
                if (line.startsWith("#")) {
                    for (String kv : line.split("\t"))
                        if (kv.startsWith("gameAssemblySha256=")) pin = kv.substring(19);
                    continue;
                }
                String[] p = line.split("\t", -1);
                if (p[0].equals("F")) funcs.add(p);
                else if (p[0].equals("D")) data.add(p);
            }
        }
        String sha = currentProgram.getExecutableSHA256();
        if (pin == null || sha == null || !pin.equalsIgnoreCase(sha))
            throw new IllegalStateException("program sha256 " + sha + " does not match label pin " + pin);

        long t0 = System.currentTimeMillis();
        AddressSet entries = new AddressSet();
        for (String[] p : funcs) entries.add(toAddr(Long.parseUnsignedLong(p[1], 16)));
        println("disassembling from " + entries.getNumAddresses() + " entries");
        new DisassembleCommand(entries, null, true).applyTo(currentProgram, monitor);
        println(String.format("disassembled in %.1fs", (System.currentTimeMillis() - t0) / 1000.0));

        SymbolTable st = currentProgram.getSymbolTable();
        Listing listing = currentProgram.getListing();
        int made = 0, failed = 0, i = 0;
        for (String[] p : funcs) {
            monitor.checkCancelled();
            Address a = toAddr(Long.parseUnsignedLong(p[1], 16));
            Function f = listing.getFunctionAt(a);
            if (f == null) {
                CreateFunctionCmd cmd = new CreateFunctionCmd(null, a, null, SourceType.IMPORTED);
                if (cmd.applyTo(currentProgram, monitor)) f = listing.getFunctionAt(a);
            }
            if (f == null) {
                failed++;
                st.createLabel(a, p[2], SourceType.IMPORTED);
            } else {
                made++;
                f.setName(p[2], SourceType.IMPORTED);
            }
            if (!p[3].isEmpty())
                for (String alias : p[3].split("\\|"))
                    st.createLabel(a, alias, SourceType.IMPORTED);
            listing.setComment(a, CodeUnit.PLATE_COMMENT, p[4]);
            if (++i % 20000 == 0)
                println(String.format("functions %d/%d (%.0fs)", i, funcs.size(), (System.currentTimeMillis() - t0) / 1000.0));
        }
        for (String[] p : data) {
            Address a = toAddr(Long.parseUnsignedLong(p[1], 16));
            st.createLabel(a, p[2], SourceType.IMPORTED);
            if (!p[4].isEmpty()) listing.setComment(a, CodeUnit.EOL_COMMENT, p[4]);
        }
        println(String.format("ImportOeSymbols: %d functions, %d label-only (no function), %d data labels, %.1fs",
            made, failed, data.size(), (System.currentTimeMillis() - t0) / 1000.0));
    }
}
