package com.github.catvod.spider;

import android.content.Context;
import com.github.catvod.crawler.Spider;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

/**
 * Owned dynamic home: merges every approved provider instead of first-answer-wins.
 *
 * 原实现是"优先级失败切换"：`if (list.length() > 0) return list;`。
 * 采集站的模糊搜索**永远**返回非空（搜「狂飙」会回来几十条不相关的短剧），
 * 于是第一个 provider 永远独占结果，点进去只有那一个源的线路——
 * 用户看到的"点开某部剧只有 bfzym3u8 一条线路"就是这个。
 *
 * 这里改成：并发问所有上游 → 按标题归一化合并 → 精确匹配独占结果。
 * 同一部剧只出现一行，线路来自所有命中的上游，每条线路自带来源名与广告提示。
 * 合并放在客户端插件里（而不是服务端），是为了让固定版本的静态配置也能有完整能力。
 */
public class WkcHome extends Spider {
    /** 所有来源名后面都要带这个提示：聚合里大量上游会在播放中插博彩广告。 */
    static final String NOTICE = "⚠勿信广告";
    private static final int PAGE_SIZE = 20;
    private static final long BUDGET_MS = 8000;
    private static final int CACHE_MAX = 8;
    private static final int RESULT_MAX = 200;

    protected final ArrayList<WkcCms> providers = new ArrayList<>();
    private final LinkedHashMap<String, Cached> cache = new LinkedHashMap<>();

    private static final class Cached {
        final JSONArray list;
        final long at;
        Cached(JSONArray list, long at) { this.list = list; this.at = at; }
    }

    @Override public void init(Context c, String ext) throws Exception {
        JSONArray sources = new JSONObject(ext).getJSONArray("providers");
        providers.clear();
        for (int i = 0; i < sources.length(); i++) {
            WkcCms s = new WkcCms();
            s.init(c, sources.getJSONObject(i).toString());
            providers.add(s);
        }
        if (providers.isEmpty()) throw new IllegalStateException("No approved home provider");
    }

    private WkcCms owner(String id) throws Exception {
        String provider = WkcNet.unpack(id).getString("provider");
        for (WkcCms s : providers) if (s.provider.equals(provider)) return s;
        throw new IllegalArgumentException("Unknown provider");
    }

    /* ---------- 标题归一化：跨上游对齐同一部剧 ---------- */

    /** NFKC + 去标点空白 + 小写，等同于构建端 checker.content.norm。 */
    static String norm(String value) {
        String s = java.text.Normalizer.normalize(value == null ? "" : value, java.text.Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
        return s.replaceAll("[^\\p{L}\\p{N}_]+", "");
    }

    /** 去掉「第X季/第X部/第X集」后缀，用于第二档宽松匹配。 */
    static String strip(String value) {
        return norm(value).replaceAll("(第[一二三四五六七八九十0-9]{1,3}[季部集])+$", "");
    }

    /* ---------- 首页与分类：仍是"先答者优先"，合并只对搜索有意义 ---------- */

    @Override public String homeContent(boolean f) throws Exception {
        Exception failure = null;
        for (WkcCms s : providers) try {
            JSONObject out = new JSONObject(s.homeContent(f));
            if (out.getJSONArray("list").length() == 0) continue;
            // Subtype ids differ between providers; expose names so fallback can translate them.
            JSONObject filters = out.optJSONObject("filters");
            if (filters != null) for (String key : filters.keySet()) {
                JSONArray groups = filters.getJSONArray(key);
                for (int i = 0; i < groups.length(); i++) {
                    JSONObject group = groups.getJSONObject(i); group.put("key", "type_name");
                    JSONArray values = group.getJSONArray("value");
                    for (int j = 0; j < values.length(); j++) {
                        JSONObject v = values.getJSONObject(j);
                        if (!v.optString("v").isEmpty()) v.put("v", v.getString("n"));
                    }
                }
            }
            return out.toString();
        } catch (Exception e) { failure = e; }
        if (failure != null) throw failure;
        return WkcNet.empty().toString();
    }

    @Override public String homeVideoContent() throws Exception { return homeContent(false); }

    @Override public String categoryContent(String t, String p, boolean f, HashMap<String, String> e) throws Exception {
        Exception failure = null;
        for (WkcCms s : providers) try {
            HashMap<String, String> mapped = e == null ? new HashMap<>() : new HashMap<>(e);
            String name = mapped.remove("type_name"); mapped.remove("type");
            if (name != null && !name.isEmpty()) {
                s.refresh(); String id = null;
                for (Map.Entry<String, String> entry : s.types.entrySet()) if (name.equals(entry.getValue())) { id = entry.getKey(); break; }
                if (id == null) continue;
                mapped.put("type", id);
            }
            String out = s.categoryContent(t, p, f, mapped);
            if (new JSONObject(out).getJSONArray("list").length() > 0) return out;
        } catch (Exception ex) { failure = ex; }
        if (failure != null) throw failure;
        return WkcNet.empty().toString();
    }

    /* ---------- 搜索：并发问全部上游后合并 ---------- */

    @Override public String searchContent(String w, boolean q) throws Exception { return searchContent(w, q, "1"); }

    @Override public String searchContent(String w, boolean q, String page) throws Exception {
        String key = (q ? "q:" : "s:") + norm(w);
        JSONArray all;
        synchronized (cache) {
            Cached hit = cache.get(key);
            if (hit != null && System.currentTimeMillis() - hit.at < 300000) all = hit.list;
            else {
                all = askEveryProvider(w, q);
                if (cache.size() >= CACHE_MAX) cache.clear();
                cache.put(key, new Cached(all, System.currentTimeMillis()));
            }
        }
        return slice(all, page);
    }

    /** 每个上游都是独立实例，可并行；总预算固定，慢的上游不拖住整个搜索。 */
    private JSONArray askEveryProvider(String w, boolean q) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(Math.max(1, Math.min(providers.size(), 6)));
        ArrayList<Future<String>> jobs = new ArrayList<>();
        try {
            for (WkcCms s : providers) jobs.add(pool.submit(() -> s.searchContent(w, q, "1")));
            long deadline = System.currentTimeMillis() + BUDGET_MS;
            ArrayList<JSONObject> items = new ArrayList<>();
            for (Future<String> job : jobs) {
                long left = deadline - System.currentTimeMillis();
                if (left <= 0) break;
                try {
                    JSONArray list = new JSONObject(job.get(left, TimeUnit.MILLISECONDS)).optJSONArray("list");
                    if (list == null) continue;
                    for (int i = 0; i < list.length(); i++) {
                        JSONObject v = list.optJSONObject(i);
                        // 上游可能已经给出空 id（测试夹具）或非对象项，一律跳过。
                        if (v != null && !v.optString("vod_id").isEmpty() && !v.optString("vod_name").isEmpty()) items.add(v);
                    }
                } catch (Exception ignore) { /* 单个上游超时或报错不影响其他上游 */ }
            }
            return merge(w, items);
        } finally {
            pool.shutdownNow();
        }
    }

    /** 精确匹配独占结果；同一部剧合并成一行，vod_id 里带上所有命中上游的 token。 */
    private JSONArray merge(String word, ArrayList<JSONObject> items) throws Exception {
        LinkedHashMap<String, ArrayList<JSONObject>> groups = new LinkedHashMap<>();
        for (JSONObject v : items) groups.computeIfAbsent(norm(v.optString("vod_name")), k -> new ArrayList<>()).add(v);

        String target = norm(word), loose = strip(word);
        ArrayList<JSONObject> exact = new ArrayList<>(), near = new ArrayList<>();
        for (Map.Entry<String, ArrayList<JSONObject>> e : groups.entrySet()) {
            ArrayList<JSONObject> group = e.getValue();
            LinkedHashSet<String> seen = new LinkedHashSet<>();
            for (JSONObject v : group) seen.add(v.optString("vod_id"));
            JSONArray ids = new JSONArray();
            for (String id : seen) ids.put(id);

            JSONObject best = group.get(0);
            JSONObject item = new JSONObject(best.toString());
            item.put("vod_id", WkcNet.pack(new JSONObject().put("home", 1)
                    .put("n", best.optString("vod_name")).put("i", ids)));
            String remarks = best.optString("vod_remarks", "");
            item.put("vod_remarks", (remarks.isEmpty() ? "" : remarks + " ") + "[" + ids.length() + "源]");
            item.put("_sources", ids.length());

            if (e.getKey().equals(target)) exact.add(item);
            else if (!loose.isEmpty() && (e.getKey().equals(loose) || e.getKey().startsWith(loose))) near.add(item);
        }
        Comparator<JSONObject> bySources = (a, b) -> b.optInt("_sources") - a.optInt("_sources");
        exact.sort(bySources); near.sort(bySources);

        ArrayList<JSONObject> out = new ArrayList<>(exact);
        // 精确匹配够多时就不再塞模糊结果，否则搜「狂飙」会被不相关的短剧淹没。
        if (exact.size() < 12) out.addAll(near);
        JSONArray result = new JSONArray();
        for (JSONObject item : out) {
            if (result.length() >= RESULT_MAX) break;
            JSONObject clean = new JSONObject(item.toString()); clean.remove("_sources");
            result.put(clean);
        }
        return result;
    }

    private String slice(JSONArray all, String page) throws Exception {
        int p = 1;
        try { p = Math.max(1, Integer.parseInt(page)); } catch (Exception ignore) { }
        int from = (p - 1) * PAGE_SIZE;
        JSONArray out = new JSONArray();
        for (int i = from; i < Math.min(all.length(), from + PAGE_SIZE); i++) out.put(all.get(i));
        int pages = Math.max(1, (all.length() + PAGE_SIZE - 1) / PAGE_SIZE);
        return new JSONObject().put("list", out).put("page", p).put("pagecount", pages)
                .put("limit", PAGE_SIZE).put("total", all.length()).toString();
    }

    /* ---------- 详情：把所有命中上游的线路合并到一起 ---------- */

    @Override public String detailContent(List<String> ids) throws Exception {
        if (ids.isEmpty()) return WkcNet.empty().toString();
        JSONObject token = WkcNet.unpack(ids.get(0));
        if (token.optInt("home", 0) == 0) return owner(ids.get(0)).detailContent(ids);

        ArrayList<String> flags = new ArrayList<>(), lines = new ArrayList<>();
        LinkedHashSet<String> used = new LinkedHashSet<>();
        JSONObject base = null;
        JSONArray packed = token.optJSONArray("i");
        for (int i = 0; packed != null && i < packed.length(); i++) {
            String single = packed.optString(i);
            if (single.isEmpty()) continue;
            try {
                JSONObject out = new JSONObject(owner(single).detailContent(Collections.singletonList(single)));
                JSONArray arr = out.optJSONArray("list");
                if (arr == null || arr.length() == 0) continue;
                JSONObject v = arr.getJSONObject(0);
                if (base == null) base = v;
                String[] fs = v.optString("vod_play_from").split("\\$\\$\\$", -1);
                String[] ls = v.optString("vod_play_url").split("\\$\\$\\$", -1);
                for (int k = 0; k < Math.min(fs.length, ls.length); k++) {
                    if (ls[k].isEmpty()) continue;
                    String shown = fs[k];
                    for (int n = 2; !used.add(shown); n++) shown = fs[k] + "·" + n;
                    flags.add(shown); lines.add(ls[k]);
                }
            } catch (Exception ignore) { /* 某个上游这条挂了，其他上游的线路照常给 */ }
        }
        if (base == null) return WkcNet.empty().toString();
        JSONObject out = new JSONObject(base.toString());
        out.put("vod_id", ids.get(0));
        out.put("vod_play_from", WkcCms.join(flags, "$$$"));
        out.put("vod_play_url", WkcCms.join(lines, "$$$"));
        return new JSONObject().put("list", new JSONArray().put(out)).toString();
    }

    @Override public String playerContent(String flag, String id, List<String> v) throws Exception {
        // 播放路线完全由 token 决定；传入的 flag 可能被上层的线路去重改写过，
        // 所以一律用 token 里记录的那一个。校验仍在上游适配器里做（原始 flag + 媒体域名 + 重新取详情）。
        JSONObject token = WkcNet.unpack(id);
        return owner(id).playerContent(token.optString("flag", flag), id, v);
    }
}
