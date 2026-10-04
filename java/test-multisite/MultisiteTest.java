package com.github.catvod.spider;
import java.util.*;
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
        check(line.equals("测试源 "+WkcHome.NOTICE),"Line must show the source name and the ad notice");
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
        WkcNative nativeSite=new WkcNative();nativeSite.init(null,"{\"id\":\"test-native\",\"adapter\":\"JpysGuard\"}");
        check(new JSONObject(nativeSite.searchContent("正常影片",false)).getJSONArray("list").length()==1,"Native legacy two-argument search");
        check(new JSONObject(nativeSite.searchContent("正常影片",false,"1")).getJSONArray("list").length()==1,"Native page one uses supported overload");
        check(new JSONObject(nativeSite.searchContent("色情",false)).getJSONArray("list").length()==0,"Native policy blocks adult query");
        System.out.println("PASS: "+assertions+" dynamic CMS content-path assertions");
    }
}
