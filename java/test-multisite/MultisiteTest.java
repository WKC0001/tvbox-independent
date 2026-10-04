package com.github.catvod.spider;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

public final class MultisiteTest {
    static int assertions;
    static void check(boolean value,String message){assertions++;if(!value)throw new AssertionError(message);}
    interface Action{void run()throws Exception;}
    static void rejects(Action call)throws Exception{boolean rejected=false;try{call.run();}catch(Exception e){rejected=true;}check(rejected,"Expected rejection");}
    static final class Fixture extends WkcCms {
        boolean pollution=false;
        protected JSONObject request(String... args)throws Exception{
            Map<String,String> q=new HashMap<>();for(int i=0;i<args.length;i+=2)q.put(args[i],args[i+1]);
            JSONArray classes=new JSONArray().put(new JSONObject().put("type_id","1").put("type_name","电影"))
                .put(new JSONObject().put("type_id","6").put("type_name","动作片"))
                .put(new JSONObject().put("type_id","9").put("type_name","里番动漫"));
            JSONArray list=new JSONArray();
            if(!"1".equals(q.get("t")))for(int i=0;i<31;i++){
                String id=""+i;if(q.containsKey("ids")&&!id.equals(q.get("ids")))continue;
                if(q.containsKey("wd")&&!"影片0".equals(q.get("wd")))continue;
                JSONObject v=new JSONObject().put("vod_id",id).put("vod_name","影片"+i)
                    .put("type_id",i==30||pollution?"9":"6").put("type_name",i==30||pollution?"里番动漫":"动作片")
                    .put("vod_pic","https://images.example/poster.jpg")
                    .put("vod_play_from","main$$$unapproved")
                    .put("vod_play_url","正片$https://media.example/"+id+".m3u8$$$引流$https://unapproved.example/page");
                list.put(v);
            }
            return new JSONObject().put("class",classes).put("list",list).put("page",q.getOrDefault("pg","1")).put("pagecount",12);
        }
    }
    static final class FallbackFixture extends WkcCms {
        String type;boolean fail;String received;
        FallbackFixture(String type,boolean fail){this.type=type;this.fail=fail;}
        protected void refresh(){types.put(type,"动作片");}
        public String categoryContent(String t,String p,boolean f,HashMap<String,String> e)throws Exception{
            received=e.get("type");
            if(fail)throw new java.io.IOException("Provider outage");
            if(!type.equals(received))throw new IllegalStateException("Untranslated category id");
            return new JSONObject().put("list",new JSONArray().put(new JSONObject().put("vod_name","正常影片"))).toString();
        }
    }
    /** 两个上游各自返回同一部剧，用来验证"合并成一行"而不是"先答者独占"。 */
    static final class SearchFixture extends WkcCms {
        private final String title;
        SearchFixture(String key,String title){this.provider=key;this.title=title;}
        public String searchContent(String w,boolean q,String page)throws Exception{
            JSONArray list=new JSONArray();
            list.put(new JSONObject().put("vod_name",title).put("vod_remarks","更新至30集")
                .put("type_id","6").put("type_name","动作片").put("vod_id",WkcNet.pack(token(title))));
            list.put(new JSONObject().put("vod_name","无关条目").put("type_id","6").put("type_name","动作片")
                .put("vod_id",WkcNet.pack(token("x"))));
            return new JSONObject().put("list",list).put("page",1).put("pagecount",1).put("limit",20).put("total",2).toString();
        }
    }
    /** 一次返回任意一批标题，用来验证"哪些该合、哪些不该合"。 */
    static final class TitlesFixture extends WkcCms {
        private final String[] titles;
        TitlesFixture(String key,String... titles){this.provider=key;this.titles=titles;}
        public String searchContent(String w,boolean q,String page)throws Exception{
            JSONArray list=new JSONArray();
            for(String t:titles)list.put(new JSONObject().put("vod_name",t).put("vod_remarks","更新至30集")
                .put("type_id","6").put("type_name","动作片").put("vod_id",WkcNet.pack(token(t))));
            return new JSONObject().put("list",list).put("page",1).put("pagecount",1).put("limit",20).put("total",titles.length).toString();
        }
    }
    /** 同一个上游有多条线路（蓝光/标清），用来验证线路名不会塌成一个被去重成「·2」「·3」。 */
    static class LinesFixture extends WkcCms {
        protected void refresh(){types.put("6","动作片");}
        protected JSONObject request(String... args)throws Exception{
            Map<String,String> q=new HashMap<>();for(int i=0;i<args.length;i+=2)q.put(args[i],args[i+1]);
            if("list".equals(q.get("ac")))
                return new JSONObject().put("class",new JSONArray().put(new JSONObject().put("type_id","6").put("type_name","动作片")));
            JSONObject v=new JSONObject().put("vod_id","1").put("vod_name","假面良人")
                .put("type_id","6").put("type_name","动作片")
                .put("vod_play_from","蓝光$$$标清")
                .put("vod_play_url","第1集$https://media.example/a.m3u8#第2集$https://media.example/b.m3u8"
                                  +"$$$第1集$https://media.example/c.m3u8");
            return new JSONObject().put("list",new JSONArray().put(v));
        }
        public String searchContent(String w,boolean q,String page)throws Exception{
            return new JSONObject().put("list",new JSONArray().put(new JSONObject().put("vod_name","假面良人")
                .put("type_id","6").put("type_name","动作片").put("vod_id",WkcNet.pack(token("1"))))).toString();
        }
    }
    /** 记录上游被"取详情"问了几次：用来证明缓存命中时不重复拉，也证明校验没被悄悄跳过。 */
    static final class CountingFixture extends LinesFixture {
        int detailRequests;
        @Override protected JSONObject request(String... args)throws Exception{
            for(String a:args)if("ids".equals(a))detailRequests++;
            return super.request(args);
        }
    }
    /** 证明首页/分类是"同时问"而不是"挨个问"：每个上游都先报个到，再等其他几家也报到了才返回。
        串行实现下第一个会一直等不到第二个（卡满 5 秒后失败），所以这不是靠计时的软断言。 */
    static final class ConcurrencyFixture extends WkcCms {
        final CountDownLatch arrived;boolean stalled;
        ConcurrencyFixture(CountDownLatch arrived){this.arrived=arrived;}
        private String answer()throws Exception{
            arrived.countDown();
            if(!arrived.await(5,TimeUnit.SECONDS))stalled=true;
            return new JSONObject().put("list",new JSONArray().put(new JSONObject().put("vod_name","正常影片"))).toString();
        }
        @Override public String homeContent(boolean f)throws Exception{return answer();}
        @Override public String categoryContent(String t,String p,boolean f,HashMap<String,String> e)throws Exception{return answer();}
    }
    /** 一家挂死不应该拖住整个首页：实测单个上游偶发能拖到 30 秒，
        如果把它排在前面、又让它独占整个预算，首屏就得跟着等满。 */
    static final class StalledFixture extends WkcCms {
        boolean asked;
        private String answer()throws Exception{
            asked=true;Thread.sleep(60000);
            return new JSONObject().put("list",new JSONArray()).toString();
        }
        @Override public String homeContent(boolean f)throws Exception{return answer();}
        @Override public String categoryContent(String t,String p,boolean f,HashMap<String,String> e)throws Exception{return answer();}
    }
    /** 数首页被问了几次：APP 会连着调 homeContent 和 homeVideoContent，
        两者内容相同，第二次必须走缓存而不是再付一轮往返。 */
    static final class HomeCountFixture extends WkcCms {
        int homeCalls;
        @Override public String homeContent(boolean f)throws Exception{
            homeCalls++;
            return new JSONObject().put("list",new JSONArray().put(new JSONObject().put("vod_name","正常影片"))).toString();
        }
    }
    static JSONObject cmsExt(String id,String label,String ad,int latency)throws Exception{
        return new JSONObject().put("id",id).put("api","https://cms.example/api").put("label",label)
            .put("media_hosts",new JSONArray().put("media.example")).put("ad_scan",ad).put("latency_ms",latency);
    }
    public static void main(String[] args)throws Exception{
        // 软色情分类名必须同时被 DENY 命中：只靠 GENRES 白名单挡是不够的，
        // 因为条目的 type_name 可能是白名单里的泛化名（如 `短剧`），真正说明问题的是 vod_class。
        for(String s:new String[]{"里番动漫","伦理片","写真","成人动漫","18禁","Hentai",
                                  "擦边短剧","理论片","福利视频","网红主播","爱蜜社"})check(WkcPolicy.genre(s)==null,"Unsafe category "+s);
        check(WkcPolicy.blocked("短剧 擦边短剧"),"Softcore class tag must be denied at item level");
        check("电影".equals(WkcPolicy.genre("动作片")),"Normal action films");
        check("动漫".equals(WkcPolicy.genre("国产动漫")),"Normal animation");
        Fixture f=new Fixture();f.init(null,new JSONObject().put("id","test").put("api","https://cms.example/api")
            .put("label","测试源")
            .put("media_hosts",new JSONArray().put("media.example")).toString());
        JSONObject home=new JSONObject(f.homeContent(true));
        check(home.getJSONArray("list").length()==30,"Dynamic catalogue must not have old 23-title cap");
        check(home.getJSONArray("class").length()==1,"Adult category removed");
        check(!home.toString().contains("vod_play_url"),"Lists must not expose playable URLs");
        JSONObject category=new JSONObject(f.categoryContent("电影","1",true,new HashMap<>()));
        check(category.getJSONArray("list").length()==30,"Empty parent falls back to child");
        check(new JSONObject(f.categoryContent("里番动漫","1",true,new HashMap<>())).getJSONArray("list").length()==0,"Direct blocked category");
        check(new JSONObject(f.searchContent("影片0",false)).getJSONArray("list").length()==30,"Search filters mixed results");
        check(new JSONObject(f.searchContent("成人",false)).getJSONArray("list").length()==0,"Adult query blocked");
        String id=home.getJSONArray("list").getJSONObject(0).getString("vod_id");
        JSONObject detail=new JSONObject(f.detailContent(Collections.singletonList(id))).getJSONArray("list").getJSONObject(0);
        String line=detail.getString("vod_play_from");
        check(line.equals("测试源 "+WkcHome.NOTICE+" · main"),
              "Line must show the source name, the ad notice and the upstream line name");
        check(detail.getString("vod_play_url").split("\\$\\$\\$",-1).length==1,"Unapproved domain removed");
        String episode=detail.getString("vod_play_url").split("\\$",2)[1];
        check(new JSONObject(f.playerContent(line,episode,new ArrayList<>())).getInt("parse")==0,"Approved direct playback through the shown line name");
        rejects(()->f.detailContent(Collections.singletonList("30")));
        rejects(()->f.detailContent(Collections.singletonList(WkcNet.pack(f.token("30")))));
        rejects(()->f.playerContent(line,"https://media.example/0.m3u8",new ArrayList<>()));
        JSONObject forged=WkcNet.unpack(episode).put("url","https://unapproved.example/x.m3u8");
        rejects(()->f.playerContent(line,WkcNet.pack(forged),new ArrayList<>()));
        // 显示名可改，但不能成为绕过"原 flag 必须仍匹配当前详情"的入口。
        JSONObject swapped=WkcNet.unpack(episode).put("raw","unapproved");
        rejects(()->f.playerContent(line,WkcNet.pack(swapped),new ArrayList<>()));
        f.pollution=true;
        rejects(()->f.detailContent(Collections.singletonList(id)));
        rejects(()->f.playerContent(line,episode,new ArrayList<>()));
        WkcHome dynamic=new WkcHome();FallbackFixture first=new FallbackFixture("6",true),second=new FallbackFixture("77",false);
        dynamic.providers.add(first);dynamic.providers.add(second);
        HashMap<String,String> subtype=new HashMap<>();subtype.put("type_name","动作片");
        check(new JSONObject(dynamic.categoryContent("电影","1",true,subtype)).getJSONArray("list").length()==1,"Fallback translates subtype names");
        check("6".equals(first.received)&&"77".equals(second.received),"Provider ids must not leak across fallback");
        WkcHome merged=new WkcHome();
        merged.providers.add(new SearchFixture("cms_a","繁华"));
        merged.providers.add(new SearchFixture("cms_b","繁华"));
        JSONObject hit=new JSONObject(merged.searchContent("繁华",false));
        check(hit.getJSONArray("list").length()==1,"The same title from two providers merges into one row");
        JSONObject row=hit.getJSONArray("list").getJSONObject(0);
        check("繁华".equals(row.getString("vod_name")),"Merged row keeps the title");
        check(row.getString("vod_remarks").contains("[2源]"),"Merged row reports how many providers matched");
        JSONObject mergedToken=WkcNet.unpack(row.getString("vod_id"));
        check(mergedToken.getInt("home")==1&&mergedToken.getJSONArray("i").length()==2,"Merged id carries every provider token");
        check(!hit.getJSONArray("list").toString().contains("无关条目"),"Unrelated titles are not padded into an exact hit");
        // 同一部剧的不同版本后缀必须并成一行：实测上游对同一部剧的标题常年不一致，
        // 按完整标题分组会让它各占一行、每行只带一部分源，看起来源多其实每行只有一个。
        WkcHome versions=new WkcHome();
        versions.providers.add(new TitlesFixture("cms_a","繁华第二季"));
        versions.providers.add(new TitlesFixture("cms_b","繁华"));
        JSONObject seasonHit=new JSONObject(versions.searchContent("繁华",false));
        check(seasonHit.getJSONArray("list").length()==1,"A season suffix must not split one show into two rows");
        check(seasonHit.getJSONArray("list").getJSONObject(0).getString("vod_remarks").contains("[2源]"),
              "The base title and its season merge into one row carrying both providers");
        // 反过来，"多几个字"不等于"同一部剧"。宽松档若不加长度约束，
        // 搜「繁华」会带出「繁华照春晚」，搜「狂飙」会带出「狂飙之浴血玫瑰」。
        WkcHome noisy=new WkcHome();
        noisy.providers.add(new TitlesFixture("cms_a","繁华","繁华照春晚","繁华之乱世情缘"));
        JSONObject noisyHit=new JSONObject(noisy.searchContent("繁华",false));
        check(noisyHit.getJSONArray("list").length()==1,"A plain title returns only the show itself");
        check(!noisyHit.getJSONArray("list").toString().contains("繁华照春晚"),
              "A title sharing three extra characters is a different show, not a version");
        check(!noisyHit.getJSONArray("list").toString().contains("繁华之乱世情缘"),
              "A derivative title is a different show, not another version of this one");
        // 播放页只显示一个源的线路，是因为首页/分类仍是"先答者优先"：凭证里只有一个上游。
        // 详情页必须按片名回问其余上游补齐，并且把同一个上游的多条线路各自标出来。
        WkcHome completed=new WkcHome();
        LinesFixture fast=new LinesFixture(),slow=new LinesFixture();
        fast.init(null,cmsExt("cms_a","甲","clean",900).toString());fast.order=0;
        slow.init(null,cmsExt("cms_b","乙","pending",300).toString());slow.order=1;
        completed.providers.add(fast);completed.providers.add(slow);
        JSONObject filled=new JSONObject(completed.detailContent(
                Collections.singletonList(WkcNet.pack(fast.token("1"))))).getJSONArray("list").getJSONObject(0);
        String[] routes=filled.getString("vod_play_from").split("\\$\\$\\$",-1);
        check(routes.length==4,"A single-source detail must be completed with the other providers' lines");
        check(routes[0].startsWith("甲")&&routes[2].startsWith("乙"),
              "The OCR-clean provider ranks first even though it answered slower");
        check(routes[0].endsWith("· 蓝光")&&routes[1].endsWith("· 标清"),
              "One provider's own lines stay distinguishable instead of collapsing into ·2 / ·3");
        String firstEpisode=filled.getString("vod_play_url").split("\\$\\$\\$",-1)[0].split("#")[0].split("\\$",2)[1];
        check(new JSONObject(completed.playerContent(routes[0],firstEpisode,new ArrayList<>())).getInt("parse")==0,
              "A completed detail still plays through the token, not through the display name");
        // 详情页最贵的一段是"逐个拉每家的详情"（实测 6 家串行累加 6.7s）。
        // 它改成并发、结果进缓存之后，线路一条都不能少、顺序也不能被并发打乱——
        // 快只能来自"不再重复等待"，不能来自"少给几条"。
        WkcHome memo=new WkcHome();
        CountingFixture cf=new CountingFixture(),cg=new CountingFixture();
        cf.init(null,cmsExt("cms_a","甲","clean",900).toString());cf.order=0;
        cg.init(null,cmsExt("cms_b","乙","pending",300).toString());cg.order=1;
        memo.providers.add(cf);memo.providers.add(cg);
        String solo=WkcNet.pack(cf.token("1"));
        String[] firstRun=new JSONObject(memo.detailContent(Collections.singletonList(solo)))
                .getJSONArray("list").getJSONObject(0).getString("vod_play_from").split("\\$\\$\\$",-1);
        int spent=cf.detailRequests+cg.detailRequests;
        check(firstRun.length==4,"A completed detail carries every provider's lines");
        String[] secondRun=new JSONObject(memo.detailContent(Collections.singletonList(solo)))
                .getJSONArray("list").getJSONObject(0).getString("vod_play_from").split("\\$\\$\\$",-1);
        check(Arrays.equals(firstRun,secondRun),
              "A cached detail must deliver the same lines in the same order");
        check(cf.detailRequests+cg.detailRequests==spent,
              "A cached detail must not re-ask the providers");
        // 并发收集不能把线路顺序变成随机的：两个互不相干的实例必须给出同样的顺序。
        WkcHome orderA=new WkcHome(),orderB=new WkcHome();
        LinesFixture a1=new LinesFixture(),a2=new LinesFixture(),b1=new LinesFixture(),b2=new LinesFixture();
        a1.init(null,cmsExt("cms_a","甲","clean",900).toString());a1.order=0;
        a2.init(null,cmsExt("cms_b","乙","pending",300).toString());a2.order=1;
        b1.init(null,cmsExt("cms_a","甲","clean",900).toString());b1.order=0;
        b2.init(null,cmsExt("cms_b","乙","pending",300).toString());b2.order=1;
        orderA.providers.add(a1);orderA.providers.add(a2);
        orderB.providers.add(b1);orderB.providers.add(b2);
        String[] left=new JSONObject(orderA.detailContent(Collections.singletonList(WkcNet.pack(a1.token("1")))))
                .getJSONArray("list").getJSONObject(0).getString("vod_play_from").split("\\$\\$\\$",-1);
        String[] right=new JSONObject(orderB.detailContent(Collections.singletonList(WkcNet.pack(b1.token("1")))))
                .getJSONArray("list").getJSONObject(0).getString("vod_play_from").split("\\$\\$\\$",-1);
        check(Arrays.equals(left,right),"Concurrent gathering must not randomise the line order");
        // 播放的路线核对刻意不缓存：每点一集都拿实时详情去比。
        // 这里能省一次 0.5~1.6s 的往返，但代价是"上游刚把内容改成违禁"时会被放行——
        // 内容合规不接受任何放行窗口，所以这个慢点保留，性能只能从并发和详情页缓存上找。
        WkcHome cold=new WkcHome();
        CountingFixture coldA=new CountingFixture();
        coldA.init(null,cmsExt("cms_a","甲","clean",900).toString());coldA.order=0;
        cold.providers.add(coldA);
        String coldFlag="甲 "+WkcHome.NOTICE+" · 蓝光";
        String coldToken=WkcNet.pack(coldA.token("1").put("flag",coldFlag).put("raw","蓝光")
                .put("url","https://media.example/a.m3u8"));
        int coldBefore=coldA.detailRequests;
        check(new JSONObject(cold.playerContent(coldFlag,coldToken,new ArrayList<>())).getInt("parse")==0,
              "Playback resolves through the token");
        check(coldA.detailRequests==coldBefore+1,"Every playback checks the route against a live detail");
        check(new JSONObject(cold.playerContent(coldFlag,coldToken,new ArrayList<>())).getInt("parse")==0,
              "A second playback still resolves");
        check(coldA.detailRequests==coldBefore+2,
              "The route check is never served from a memory, even for a title just opened");
        String playLine=firstRun[0];
        String playEpisode=new JSONObject(memo.detailContent(Collections.singletonList(solo)))
                .getJSONArray("list").getJSONObject(0).getString("vod_play_url").split("\\$\\$\\$",-1)[0].split("#")[0].split("\\$",2)[1];
        check(new JSONObject(memo.playerContent(playLine,playEpisode,new ArrayList<>())).getInt("parse")==0,
              "A completed detail still plays through its own token");
        // 核对本身一行没删：伪造 url 与未经批准的域名都照旧被拒。
        String forgedEpisode=WkcNet.pack(WkcNet.unpack(playEpisode).put("url","https://unapproved.example/x.m3u8"));
        rejects(()->memo.playerContent(playLine,forgedEpisode,new ArrayList<>()));
        // 反过来：没有扫描证据的源不能被当成"干净"排在前面——没扫过就是没扫过。
        WkcHome unscanned=new WkcHome();
        LinesFixture pending=new LinesFixture(),flagged=new LinesFixture();
        pending.init(null,cmsExt("cms_a","甲","pending",300).toString());pending.order=0;
        flagged.init(null,cmsExt("cms_b","乙","flagged",900).toString());flagged.order=1;
        unscanned.providers.add(pending);unscanned.providers.add(flagged);
        String[] risky=new JSONObject(unscanned.detailContent(
                Collections.singletonList(WkcNet.pack(flagged.token("1"))))).getJSONArray("list")
                .getJSONObject(0).getString("vod_play_from").split("\\$\\$\\$",-1);
        check(risky[0].startsWith("甲"),"A provider with gambling ads must not outrank an unscanned one");
        // 首页/分类改成并发之后，等待时间从"各家相加"变成"最慢那一家"（实测 7.25s → 1.64s）。
        // 但"先答者优先"的规则不能变成"谁先回来用谁"——那会让首页内容随机化。
        CountDownLatch barrier=new CountDownLatch(2);
        ConcurrencyFixture c1=new ConcurrencyFixture(barrier),c2=new ConcurrencyFixture(barrier);
        WkcHome parallel=new WkcHome();parallel.providers.add(c1);parallel.providers.add(c2);
        check(new JSONObject(parallel.homeContent(true)).getJSONArray("list").length()==1,"Concurrent home still returns a catalogue");
        check(!c1.stalled&&!c2.stalled,"Home providers must be asked at the same time, not one after another");
        CountDownLatch barrier2=new CountDownLatch(2);
        ConcurrencyFixture d1=new ConcurrencyFixture(barrier2),d2=new ConcurrencyFixture(barrier2);
        WkcHome parallelCategory=new WkcHome();parallelCategory.providers.add(d1);parallelCategory.providers.add(d2);
        check(new JSONObject(parallelCategory.categoryContent("电影","1",true,new HashMap<>()))
              .getJSONArray("list").length()==1,"Concurrent category still returns a listing");
        check(!d1.stalled&&!d2.stalled,"Category providers must be asked at the same time, not one after another");
        // 排在最前面那家挂死时，首屏不能被它拖到超时（它要 60 秒才返回）。
        WkcHome stallHome=new WkcHome();
        StalledFixture stuck=new StalledFixture();ConcurrencyFixture ok1=new ConcurrencyFixture(new CountDownLatch(1));
        stallHome.providers.add(stuck);stallHome.providers.add(ok1);
        long began=System.currentTimeMillis();
        check(new JSONObject(stallHome.homeContent(true)).getJSONArray("list").length()==1,
              "A stalled first provider must not leave the home screen empty");
        long stallWaited=System.currentTimeMillis()-began;
        check(stallWaited<10000,"A stalled provider must not hold the home screen (waited "+stallWaited+" ms)");
        check(stuck.asked,"The stalled provider is still asked, just not waited for");
        // APP 连着问 homeContent 与 homeVideoContent：同一份首页片单只该付一次往返。
        WkcHome caching=new WkcHome();HomeCountFixture hc=new HomeCountFixture();caching.providers.add(hc);
        String homeOnce=caching.homeContent(true);int homeSpent=hc.homeCalls;
        check(homeOnce.equals(caching.homeVideoContent()),"homeVideoContent serves the same home content");
        check(hc.homeCalls==homeSpent,"The home screen must not be fetched twice in a row");
        WkcNative nativeSite=new WkcNative();nativeSite.init(null,"{\"id\":\"test-native\",\"adapter\":\"JpysGuard\"}");
        check(new JSONObject(nativeSite.searchContent("正常影片",false)).getJSONArray("list").length()==1,"Native legacy two-argument search");
        check(new JSONObject(nativeSite.searchContent("正常影片",false,"1")).getJSONArray("list").length()==1,"Native page one uses supported overload");
        check(new JSONObject(nativeSite.searchContent("色情",false)).getJSONArray("list").length()==0,"Native policy blocks adult query");
        System.out.println("PASS: "+assertions+" dynamic CMS content-path assertions");
    }
}
