package lc;

import skadistats.clarity.model.Entity;
import skadistats.clarity.model.FieldPath;
import skadistats.clarity.processor.entities.Entities;
import skadistats.clarity.processor.entities.OnEntityCreated;
import skadistats.clarity.processor.entities.UsesEntities;
import skadistats.clarity.processor.reader.OnTickEnd;
import skadistats.clarity.processor.runner.Context;
import skadistats.clarity.processor.runner.SimpleRunner;
import skadistats.clarity.source.MappedFileSource;

import java.util.Arrays;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.TreeMap;

/**
 * Survey probe: what can clarity actually see in this replay?
 * Prints the entity-class inventory and, for classes of interest, the property list.
 * This answers "is clarity only good for coordinates?" with evidence.
 */
@UsesEntities
public class Survey {

    private final Map<String, Integer> classCounts = new TreeMap<>();
    private final Map<String, Entity> firstOf = new LinkedHashMap<>();
    private int tick = 0;
    private boolean dumped = false;
    private String[] want;

    @OnEntityCreated
    protected void onCreated(Entity e) {
        String dn;
        try { dn = e.getDtClass().getDtName(); } catch (Exception ex) { return; }
        classCounts.merge(dn, 1, Integer::sum);
        if (isWanted(dn)) firstOf.put(dn, e);
    }

    private boolean isWanted(String dn) {
        for (String w : want) if (dn.equals(w) || dn.startsWith(w)) return true;
        return false;
    }

    @OnTickEnd
    protected void onTickEnd(Context ctx, boolean synthetic) {
        tick++;
        // snapshot properties once entities are fully populated
        if (!dumped && tick > 6000) {
            dumped = true;
            // refresh from the live entity list so we read a populated instance
            Entities list = ctx.getProcessor(Entities.class);
            if (list != null) {
                list.stream().forEach(e -> {
                    String dn;
                    try { dn = e.getDtClass().getDtName(); } catch (Exception ex) { return; }
                    if (isWanted(dn)) firstOf.put(dn, e);
                });
            }
            dumpProperties();
        }
    }

    private java.util.List<String> propertiesOf(Entity e) {
        java.util.List<String> out = new java.util.ArrayList<>();
        try {
            Iterator<FieldPath> it = e.getState().fieldPathIterator();
            while (it.hasNext()) {
                FieldPath fp = it.next();
                String n = e.getNameForFieldPath(fp);
                if (n != null) out.add(n);
            }
        } catch (Exception ex) {
            out.add("<error: " + ex + ">");
        }
        return out;
    }

    private void dumpProperties() {
        System.out.println();
        System.out.println("## property lists (sampled at tick " + tick + ")");
        for (String w : want) {
            Entity e = firstOf.get(w);
            if (e == null) {
                for (Map.Entry<String, Entity> en : firstOf.entrySet()) {
                    if (en.getKey().startsWith(w)) { e = en.getValue(); w = en.getKey(); break; }
                }
            }
            if (e == null) { System.out.println("\n### " + w + "  (NOT PRESENT)"); continue; }
            java.util.List<String> names = propertiesOf(e);
            System.out.println("\n### " + w + "   index=" + e.getIndex()
                    + "   existent=" + e.isExistent() + "   active=" + e.isActive()
                    + "   properties=" + names.size());
            int shown = 0;
            for (String p : names) {
                if (shown++ >= 90) { System.out.println("    ... (" + (names.size() - 90) + " more)"); break; }
                Object v = null;
                try { v = e.getProperty(p); } catch (Exception ignored) {}
                String s = String.valueOf(v);
                if (s.length() > 40) s = s.substring(0, 40) + "...";
                System.out.printf("      %-50s %s%n", p, s);
            }
        }
    }

    public void run(String[] args) throws Exception {
        String replay = args[0];
        want = args.length > 1 ? Arrays.copyOfRange(args, 1, args.length)
                : new String[]{"CDOTA_Unit_Hero_Legion_Commander", "CDOTA_PlayerResource",
                               "CDOTA_DataRadiant", "CDOTA_DataDire"};
        try (MappedFileSource s = new MappedFileSource(replay)) {
            new SimpleRunner(s).runWith(this);
        }
        System.out.println("# ticks=" + tick + "  distinct entity classes=" + classCounts.size());
        System.out.println();
        System.out.println("## entity classes, with instance count");
        classCounts.forEach((k, v) -> System.out.printf("   %-62s %6d%n", k, v));
    }

    public static void main(String[] args) throws Exception {
        new Survey().run(args);
    }
}
