package lc;

import skadistats.clarity.model.Entity;
import skadistats.clarity.processor.entities.OnEntityCreated;
import skadistats.clarity.processor.entities.UsesEntities;
import skadistats.clarity.processor.reader.OnTickEnd;
import skadistats.clarity.processor.runner.SimpleRunner;
import skadistats.clarity.source.MappedFileSource;

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Dumps per-tick hero state from a Dota 2 Source 2 replay using clarity 5.0.1.
 * Output CSV: gametime,tick,index,dtname,team,heroid,x,y,hp,maxhp,level,lifestate
 * Usage: java -jar dota-lc-parse.jar <replay.dem> [out.csv] [sampleEveryTicks]
 */
@UsesEntities
public class ReplayDump {

    private final Map<Integer, Entity> heroesByIndex = new LinkedHashMap<>();
    private PrintWriter out;
    private int tick = 0;
    private int sampleEvery = 15;
    private long samples = 0;

    @OnEntityCreated
    protected void onEntityCreated(Entity e) {
        String n;
        try {
            n = e.getDtClass().getDtName();
        } catch (Exception ex) {
            return;
        }
        if (n.startsWith("CDOTA_Unit_Hero_")) {
            heroesByIndex.put(e.getIndex(), e);
        }
    }

    @OnTickEnd
    protected void onTickEnd(boolean synthetic) {
        if (tick % sampleEvery == 0) {
            dumpTick();
        }
        tick++;
    }

    private double gameTime() {
        // m_pGameRules.m_fGameTime is not readable through clarity on current builds, so the
        // raw demo clock (tick / 30) is exported instead. It is NOT the in-game clock: the
        // difference is a constant offset (game start plus any pre-game time) that must be
        // solved per match by aligning death moments with the scoreboard. See ticks_coach.py.
        return tick / 30.0;
    }

    private void dumpTick() {
        double t = gameTime();
        for (Map.Entry<Integer, Entity> en : heroesByIndex.entrySet()) {
            Entity h = en.getValue();
            Float x = pos(h, "cellX", "vecX");
            Float y = pos(h, "cellY", "vecY");
            if (x == null || y == null) continue;
            out.printf(Locale.ROOT, "%.2f,%d,%d,%s,%d,%d,%.1f,%.1f,%d,%d,%d,%d%n",
                    t, tick, en.getKey(), h.getDtClass().getDtName(),
                    num(h, "m_iTeamNum"), num(h, "m_nHeroID"),
                    x, y, num(h, "m_iHealth"), num(h, "m_iMaxHealth"),
                    num(h, "m_iCurrentLevel"), num(h, "m_lifeState"));
            samples++;
        }
    }

    private Float pos(Entity e, String cell, String vec) {
        try {
            Object c = e.getProperty("CBodyComponent.m_" + cell);
            Object v = e.getProperty("CBodyComponent.m_" + vec);
            if (!(c instanceof Number) || !(v instanceof Number)) return null;
            return ((Number) c).intValue() * 128.0f + ((Number) v).floatValue();
        } catch (Exception ex) {
            return null;
        }
    }

    private int num(Entity e, String name) {
        try {
            if (!e.hasProperty(name)) return -1;
            Object o = e.getProperty(name);
            return (o instanceof Number) ? ((Number) o).intValue() : -1;
        } catch (Exception ex) {
            return -1;
        }
    }

    public void run(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("usage: java -jar dota-lc-parse.jar <replay.dem> [out.csv] [sampleEveryTicks]");
            System.exit(2);
        }
        String replay = args[0];
        String outPath = args.length > 1 ? args[1] : null;
        if (args.length > 2) sampleEvery = Integer.parseInt(args[2]);
        out = (outPath != null)
                ? new PrintWriter(new BufferedWriter(new FileWriter(outPath)))
                : new PrintWriter(System.out);
        out.println("gametime,tick,index,dtname,team,heroid,x,y,hp,maxhp,level,lifestate");

        long t0 = System.currentTimeMillis();
        try (MappedFileSource s = new MappedFileSource(replay)) {
            new SimpleRunner(s).runWith(this);
        }
        out.flush();
        if (outPath != null) out.close();
        System.err.printf(Locale.ROOT, "done: %d ticks, %d hero-samples, %.1fs, heroes=%d%n",
                tick, samples, (System.currentTimeMillis() - t0) / 1000.0, heroesByIndex.size());
        System.err.println("hero classes:");
        heroesByIndex.values().forEach(h ->
                System.err.println("  idx=" + h.getIndex() + "  " + h.getDtClass().getDtName()));
    }

    public static void main(String[] args) throws Exception {
        new ReplayDump().run(args);
    }
}
