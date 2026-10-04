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
    /** 详情页补源用的预算要更短：这里已经在等一个详情了，多等一秒用户就多等一秒。 */
    private static final long DETAIL_BUDGET_MS = 5000;
    /** 并行取各家详情的总预算。实测单个上游 0.5~1.6s，6s 足够让 6 家全部返回，
        所以正常情况一条线路都不会少。预算只是兜底：真遇上游抽风时不再让用户干等，
        没赶上的那一家这一轮不参与合并，下一次点开照常重来——不会永久放弃它。 */
    private static final long COMBINE_BUDGET_MS = 6000;
    private static final int CACHE_MAX = 8;
    private static final int RESULT_MAX = 200;
    private static final long CACHE_TTL_MS = 300000;
    /** 合并后的详情只缓存 60 秒，比搜索结果的 5 分钟短得多。
        详情页里带着"这一条能不能播"的结论（各上游的详情都过了内容检查），
        把它记 5 分钟等于让一条刚变成违禁的内容继续出现 5 分钟。
        60 秒足够覆盖"从播放返回列表再点进来"这个真正需要快的场景。 */
    private static final long DETAIL_TTL_MS = 60000;
    /** 首页/分类的总预算。必须大于单次上游请求自己的超时（WkcNet 是 8s 连接 + 10s 读取），
        否则会把一个"再等一秒就成功"的请求掐掉，平白变成一次失败。
        并发之后正常情况是 1.6s 就全部回来了，这个 20s 只在多家同时抽风时才起作用。 */
    private static final long LIST_BUDGET_MS = 20000;
    /** 首页结果缓存 60 秒。APP 会连着问 homeContent 和 homeVideoContent，
        两者内容一样（都是首页片单），不缓存等于同一份数据付两次往返。
        这里缓存的只是"片单列表"——列表项在 WkcCms.filtered() 里已经删掉了播放地址，
        不含任何可播放结论，所以缓存它不涉及内容合规。 */
    private static final long HOME_TTL_MS = 60000;

    protected final ArrayList<WkcCms> providers = new ArrayList<>();
    private final LinkedHashMap<String, Cached> cache = new LinkedHashMap<>();
    private String homeBody;
    private long homeStamp;

    private static final class Cached {
        final JSONArray list;
        /** 合并后的详情也缓存在这里（与搜索结果共用容量和 TTL）。 */
        final JSONObject detail;
        final long at;
        Cached(JSONArray list, long at) { this(list, null, at); }
        Cached(JSONArray list, JSONObject detail, long at) { this.list = list; this.detail = detail; this.at = at; }
    }

    /** 缓存满了不要全清：全清会把刚缓存的几部剧一起扔掉，表现为"用一会儿突然集体变慢"。
        扔掉最早进来的四分之一就够了。 */
    private void trim() {
        if (cache.size() < CACHE_MAX) return;
        Iterator<String> it = cache.keySet().iterator();
        for (int n = 0; n < Math.max(1, CACHE_MAX / 4) && it.hasNext(); n++) it.remove();
    }

    private JSONObject cachedDetail(String key) {
        synchronized (cache) {
            Cached hit = cache.get(key);
            if (hit == null || hit.detail == null) return null;
            if (System.currentTimeMillis() - hit.at >= DETAIL_TTL_MS) return null;
            return new JSONObject(hit.detail.toString());
        }
    }

    private void rememberDetail(String key, JSONObject value) {
        synchronized (cache) {
            trim();
            cache.put(key, new Cached(null, value, System.currentTimeMillis()));
        }
    }

    @Override public void init(Context c, String ext) throws Exception {
        JSONArray sources = new JSONObject(ext).getJSONArray("providers");
        providers.clear();
        for (int i = 0; i < sources.length(); i++) {
            WkcCms s = new WkcCms();
            s.init(c, sources.getJSONObject(i).toString());
            s.order = i;
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

    /** 剥掉「版本 / 季数 / 集数」这类修饰后缀，用来判定两个标题说的是不是同一部剧。

     *  不去掉「之XXX」这种内容后缀：「狂飙之浴血玫瑰」是另一部剧，不是「狂飙」的另一个版本；
     *  而「庆余年第二季」「三体网飞版」「漫长的季节卫视版」确实是同一部剧的不同版本，
     *  应该并成一行——否则同一部剧会各占一行，每行只有一部分源，
     *  看起来"源很多"其实每行只有一个，这正是用户抱怨的那种假繁荣。

     *  反复剥离是因为修饰会叠加（「庆余年第二季完结」要剥两层）。
     *  实测：不加这一步，搜 8 个常见剧名会从 377 条并成 104 行；
     *  加上之后同样数据降到十几行。
     */
    static String strip(String value) {
        String s = norm(value);
        for (int i = 0; i < 4; i++) {
            String before = s;
            s = s.replaceAll("(第[一二三四五六七八九十0-9]{1,3}[季部集])$", "");
            s = s.replaceAll("(全[0-9]{1,3}集|完结|全集|高清|超清|蓝光|国语|粤语|中字|双语|未删减|无删减)$", "");
            s = s.replaceAll("(卫视|网飞|奈飞|导演|电视|加长|重制|修复|修订|特别|收藏)版$", "");
            s = s.replaceAll("[0-9]{4}$", "");          // 括号里的年份经 norm 后只剩数字
            if (s.equals(before)) break;
        }
        // 剥空了说明搜索词本身就是修饰（例如搜「第二季」），退回归一化原文。
        return s.isEmpty() ? norm(value) : s;
    }

    /* ---------- 首页与分类：仍是"先答者优先"，合并只对搜索有意义 ---------- */

    private static final class Answer { String body; Throwable error; boolean pending; }

    /** 把每个上游的任务同时发出去，再按下标顺序收结果。

        原来是一个 for 循环串行问：6 家耗时直接相加（实测串行 7.25s）。
        同时发出之后等待时间变成"最慢那一家"（实测并发 1.64s），
        而按下标顺序收取保证了"谁优先"仍然完全由 providers 顺序决定——
        常见的并发写法（谁先回来用谁）会把首页内容变成随机的，这里不要那样。
        顺序还决定了构建端必须把最快的上游排在最前面：并发之后首屏耗时 = 排第一那家的耗时。 */
    private Answer[] askInOrder(List<Callable<String>> tasks, long budget) {
        Answer[] out = new Answer[tasks.size()];
        ExecutorService pool = Executors.newFixedThreadPool(Math.max(1, Math.min(tasks.size(), 6)));
        ArrayList<Future<String>> jobs = new ArrayList<>();
        try {
            for (Callable<String> t : tasks) jobs.add(pool.submit(t));
            long deadline = System.currentTimeMillis() + budget;
            for (int i = 0; i < jobs.size(); i++) out[i] = new Answer();
            // 每一家只给总预算的一份。实测单个上游偶发能拖到 30 秒，
            // 如果把整个预算都押在排第一的那家身上，它一抽风首屏就得等满 20 秒。
            // 切片之后超时就先去看下一家，谁先回来用谁。
            long slice = Math.min(4000, Math.max(1200, budget / Math.max(1, jobs.size())));
            for (int i = 0; i < jobs.size(); i++) {
                long left = deadline - System.currentTimeMillis();
                if (left <= 0) break;
                try { out[i].body = jobs.get(i).get(Math.min(slice, left), TimeUnit.MILLISECONDS); }
                catch (TimeoutException e) { out[i].pending = true; }
                catch (Exception e) { out[i].error = e.getCause() != null ? e.getCause() : e; }
            }
            // 只在"一轮下来谁都没赶上"时才再等一轮，把剩下的预算给还在跑的那几家。
            // 已经拿到任何一份答复就立刻收工——否则又要回头去等那家挂死的。
            boolean any=false;
            for (Answer a : out) if (a.body != null) { any = true; break; }
            if (!any) for (int i = 0; i < jobs.size(); i++) {
                if (!out[i].pending) continue;
                long left = deadline - System.currentTimeMillis();
                if (left <= 0) break;
                try { out[i].body = jobs.get(i).get(left, TimeUnit.MILLISECONDS); }
                catch (Exception e) { out[i].error = e.getCause() != null ? e.getCause() : e; }
                out[i].pending = false;
            }
        } finally { pool.shutdownNow(); }
        return out;
    }

    /** 收不到任何答复时把上游的错误抛回去，不要静默给一个空首页假装没事。 */
    private static String firstUsable(Answer[] answers, String field) throws Exception {
        Throwable failure = null;
        for (Answer a : answers) {
            if (a == null) continue;
            if (a.body == null) { if (failure == null) failure = a.error; continue; }
            try {
                if (new JSONObject(a.body).getJSONArray(field).length() > 0) return a.body;
            } catch (Exception ignore) { if (failure == null) failure = ignore; }
        }
        if (failure instanceof Exception) throw (Exception) failure;
        if (failure instanceof Error) throw (Error) failure;
        return null;
    }

    private synchronized String cachedHome() {
        return System.currentTimeMillis() - homeStamp < HOME_TTL_MS ? homeBody : null;
    }

    private synchronized void rememberHome(String body) {
        homeBody = body; homeStamp = System.currentTimeMillis();
    }

    @Override public String homeContent(boolean f) throws Exception {
        // WkcCms.homeContent 不看 filter 参数，两种取值给出的是同一份内容，
        // 而 APP 会连着问 homeContent 和 homeVideoContent —— 缓存一份就能省掉整轮往返。
        String memo = cachedHome();
        if (memo != null) return memo;
        ArrayList<Callable<String>> tasks = new ArrayList<>();
        for (WkcCms s : providers) tasks.add(() -> s.homeContent(f));
        String picked = firstUsable(askInOrder(tasks, LIST_BUDGET_MS), "list");
        if (picked == null) return WkcNet.empty().toString();
        JSONObject out = new JSONObject(picked);
        // Subtype ids differ between providers; expose names so fallback can translate them.
        JSONObject filters = out.optJSONObject("filters");
        if (filters != null) for (String name : filters.keySet()) {
            JSONArray groups = filters.getJSONArray(name);
            for (int i = 0; i < groups.length(); i++) {
                JSONObject group = groups.getJSONObject(i); group.put("key", "type_name");
                JSONArray values = group.getJSONArray("value");
                for (int j = 0; j < values.length(); j++) {
                    JSONObject v = values.getJSONObject(j);
                    if (!v.optString("v").isEmpty()) v.put("v", v.getString("n"));
                }
            }
        }
        String result = out.toString();
        rememberHome(result);
        return result;
    }

    @Override public String homeVideoContent() throws Exception { return homeContent(false); }

    @Override public String categoryContent(String t, String p, boolean f, HashMap<String, String> e) throws Exception {
        ArrayList<Callable<String>> tasks = new ArrayList<>();
        for (WkcCms s : providers) tasks.add(() -> {
            HashMap<String, String> mapped = e == null ? new HashMap<>() : new HashMap<>(e);
            String name = mapped.remove("type_name"); mapped.remove("type");
            if (name != null && !name.isEmpty()) {
                s.refresh(); String id = null;
                for (Map.Entry<String, String> entry : s.types.entrySet()) if (name.equals(entry.getValue())) { id = entry.getKey(); break; }
                // 这家没有这个子分类：返回空串而不是 null，好让"跳过"和"出错"区分开。
                if (id == null) return new JSONObject().put("list", new JSONArray()).toString();
                mapped.put("type", id);
            }
            return s.categoryContent(t, p, f, mapped);
        });
        String picked = firstUsable(askInOrder(tasks, LIST_BUDGET_MS), "list");
        return picked == null ? WkcNet.empty().toString() : picked;
    }

    /* ---------- 搜索：并发问全部上游后合并 ---------- */

    @Override public String searchContent(String w, boolean q) throws Exception { return searchContent(w, q, "1"); }

    @Override public String searchContent(String w, boolean q, String page) throws Exception {
        String key = (q ? "q:" : "s:") + norm(w);
        JSONArray all;
        synchronized (cache) {
            Cached hit = cache.get(key);
            if (hit != null && System.currentTimeMillis() - hit.at < CACHE_TTL_MS) all = hit.list;
            else {
                all = askEveryProvider(w, q, BUDGET_MS);
                trim();
                cache.put(key, new Cached(all, System.currentTimeMillis()));
            }
        }
        return slice(all, page);
    }

    /** 每个上游都是独立实例，可并行；总预算固定，慢的上游不拖住整个搜索。 */
    private JSONArray askEveryProvider(String w, boolean q, long budget) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(Math.max(1, Math.min(providers.size(), 6)));
        ArrayList<Future<String>> jobs = new ArrayList<>();
        try {
            for (WkcCms s : providers) jobs.add(pool.submit(() -> s.searchContent(w, q, "1")));
            long deadline = System.currentTimeMillis() + budget;
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
        // 分组键也用 strip：「庆余年第二季」和「庆余年」是同一部剧，必须落在同一组里，
        // 否则它们各占一行、各自只带一部分源。
        for (JSONObject v : items) groups.computeIfAbsent(strip(v.optString("vod_name")), k -> new ArrayList<>()).add(v);

        String target = strip(word);
        if (target.isEmpty()) target = norm(word);
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
            // 宽松档必须严格受限：只接受"目标词是它的前缀、且多出来的不超过 2 个字"。
            // 没有这个限制，一个关键词就能带出二十几行别的剧——
            // 实测搜「狂飙」会带进「狂飙之浴血玫瑰」（多 6 字），
            // 搜「繁花」会带进「繁花照春晚」（多 3 字），搜「庆余年」全是「庆余年之XXX」。
            else if (e.getKey().startsWith(target) && e.getKey().length() <= target.length() + 2) near.add(item);
        }
        Comparator<JSONObject> bySources = (a, b) -> b.optInt("_sources") - a.optInt("_sources");
        exact.sort(bySources); near.sort(bySources);

        ArrayList<JSONObject> out = new ArrayList<>(exact);
        // 同名组够多时就不再追加宽松组：这时列表已被同一部剧的各个版本占满，
        // 再塞"多两个字"的条目只会把真正要找的那个挤下去。
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
        // 合并结果按片缓存：刚才算过一次的话直接复用。实测这一步才是详情页最贵的一段
        // （6 家详情累加 6.7s），不缓存的话五分钟内重开同一部剧要再等一遍。
        String cacheKey = "d:" + ids.get(0);
        JSONObject memo = cachedDetail(cacheKey);
        if (memo != null) return new JSONObject().put("list", new JSONArray().put(memo)).toString();
        JSONObject token = WkcNet.unpack(ids.get(0));
        if (token.optInt("home", 0) == 1) {
            ArrayList<String> all = new ArrayList<>();
            JSONArray packed = token.optJSONArray("i");
            for (int i = 0; packed != null && i < packed.length(); i++)
                if (!packed.optString(i).isEmpty()) all.add(packed.optString(i));
            JSONObject merged = combine(all, null);
            if (merged == null) return WkcNet.empty().toString();
            merged.put("vod_id", ids.get(0));
            rememberDetail(cacheKey, merged);
            return new JSONObject().put("list", new JSONArray().put(merged)).toString();
        }
        // 首页和分类仍是"先答者优先"，点进去的凭证只带一个上游——
        // 用户看到"播放页只有这一家的线路"就是这里。按片名回问其余上游补齐。
        JSONObject own = null;
        try {
            own = new JSONObject(owner(ids.get(0)).detailContent(Collections.singletonList(ids.get(0))))
                    .getJSONArray("list").getJSONObject(0);
        } catch (Exception e) { return WkcNet.empty().toString(); }
        ArrayList<String> all = new ArrayList<>();
        all.add(ids.get(0));
        for (String peer : peersOf(own.optString("vod_name"))) if (!all.contains(peer)) all.add(peer);
        JSONObject merged = combine(all, own);
        if (merged == null) return WkcNet.empty().toString();
        merged.put("vod_id", ids.get(0));
        rememberDetail(cacheKey, merged);
        return new JSONObject().put("list", new JSONArray().put(merged)).toString();
    }

    /** 按片名问其余上游，把"同一部剧"在别人那里的凭证找回来。补不到就退回单源，不报错。 */
    private ArrayList<String> peersOf(String name) throws Exception {
        ArrayList<String> out = new ArrayList<>();
        if (providers.size() < 2 || name.isEmpty()) return out;
        String key = "d:" + strip(name);
        JSONArray rows;
        synchronized (cache) {
            Cached hit = cache.get(key);
            if (hit != null && System.currentTimeMillis() - hit.at < CACHE_TTL_MS) rows = hit.list;
            else {
                rows = askEveryProvider(name, false, DETAIL_BUDGET_MS);
                trim();
                cache.put(key, new Cached(rows, System.currentTimeMillis()));
            }
        }
        String target = strip(name);
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i);
            // 只认"就是这一部"的那一行：宽松档带进来的衍生剧会把别的剧的线路混进来。
            if (row == null || !target.equals(strip(row.optString("vod_name")))) continue;
            try {
                JSONArray inner = WkcNet.unpack(row.optString("vod_id")).optJSONArray("i");
                for (int k = 0; inner != null && k < inner.length(); k++)
                    if (!inner.optString(k).isEmpty()) out.add(inner.optString(k));
            } catch (Exception ignore) { }
            break;
        }
        return out;
    }

    /** 一条线路 = 一个上游的一组集数。排序在这里定：先无广告，再快的。 */
    private static final class Route implements Comparable<Route> {
        final String flag, line;
        final int ad, latency, order;
        Route(String flag, String line, WkcCms owner) {
            this.flag = flag; this.line = line;
            this.ad = owner.adRank(); this.latency = owner.latency(); this.order = owner.order;
        }
        public int compareTo(Route o) {
            if (ad != o.ad) return ad - o.ad;
            if (latency != o.latency) return Integer.compare(latency, o.latency);
            return order - o.order;
        }
    }

    /** 并发取每一家的详情。它们之间没有依赖，串起来等纯属浪费。
        拿不到的位置留 null：一家慢或挂了，其余照常合并，绝不整页失败。 */
    private ArrayList<JSONObject> gather(List<String> ids, JSONObject seed) {
        ArrayList<JSONObject> out = new ArrayList<>();
        ArrayList<Future<JSONObject>> jobs = new ArrayList<>();
        for (int i = 0; i < ids.size(); i++) { out.add(null); jobs.add(null); }
        ExecutorService pool = Executors.newFixedThreadPool(Math.max(1, Math.min(ids.size(), 6)));
        try {
            for (int i = 0; i < ids.size(); i++) {
                // 单源凭证那条详情已经取过了，别再问一遍——它本来就在这次的等待时间里。
                if (seed != null && i == 0) { out.set(0, seed); continue; }
                final String single = ids.get(i);
                jobs.set(i, pool.submit(() -> {
                    JSONObject r = new JSONObject(owner(single).detailContent(Collections.singletonList(single)));
                    JSONArray arr = r.optJSONArray("list");
                    return (arr == null || arr.length() == 0) ? null : arr.getJSONObject(0);
                }));
            }
            long deadline = System.currentTimeMillis() + COMBINE_BUDGET_MS;
            for (int i = 0; i < jobs.size(); i++) {
                Future<JSONObject> job = jobs.get(i);
                if (job == null) continue;
                long left = deadline - System.currentTimeMillis();
                if (left <= 0) { job.cancel(true); continue; }
                try { out.set(i, job.get(left, TimeUnit.MILLISECONDS)); }
                catch (Exception ignore) { /* 这一家没赶上，其余照常合并 */ }
            }
        } finally { pool.shutdownNow(); }
        return out;
    }

    /** 把所有上游的线路并成一份详情。顺序即播放器的默认选择：第一条就是最干净最快的那条。 */
    private JSONObject combine(List<String> ids, JSONObject seed) throws Exception {
        ArrayList<Route> gathered = new ArrayList<>();
        JSONObject base = seed;
        // 按 ids 原顺序收集，所以同样的输入一定得到同样的线路顺序——不能让并发把它变成随机的。
        ArrayList<JSONObject> details = gather(ids, seed);
        for (int i = 0; i < ids.size(); i++) {
            JSONObject v = details.get(i);
            if (v == null) continue;
            if (base == null) base = v;
            WkcCms provider;
            try { provider = owner(ids.get(i)); } catch (Exception ignore) { continue; }
            String[] fs = v.optString("vod_play_from").split("\\$\\$\\$", -1);
            String[] ls = v.optString("vod_play_url").split("\\$\\$\\$", -1);
            for (int k = 0; k < Math.min(fs.length, ls.length); k++) {
                if (fs[k].isEmpty() || ls[k].isEmpty()) continue;
                gathered.add(new Route(fs[k], ls[k], provider));
            }
        }
        if (base == null) return null;
        Collections.sort(gathered);
        ArrayList<String> flags = new ArrayList<>(), lines = new ArrayList<>();
        LinkedHashSet<String> used = new LinkedHashSet<>();
        for (Route r : gathered) {
            String shown = r.flag;
            // 去重只改显示名；token 里记录的仍是原名，播放校验不受影响。
            for (int n = 2; !used.add(shown); n++) shown = r.flag + "·" + n;
            flags.add(shown); lines.add(r.line);
        }
        JSONObject out = new JSONObject(base.toString());
        out.put("vod_play_from", WkcCms.join(flags, "$$$"));
        out.put("vod_play_url", WkcCms.join(lines, "$$$"));
        return out;
    }

    @Override public String playerContent(String flag, String id, List<String> v) throws Exception {
        // 播放路线完全由 token 决定；传入的 flag 可能被上层的线路去重改写过，
        // 所以一律用 token 里记录的那一个。校验仍在上游适配器里做（原始 flag + 媒体域名 + 重新取详情）。
        JSONObject token = WkcNet.unpack(id);
        return owner(id).playerContent(token.optString("flag", flag), id, v);
    }
}
