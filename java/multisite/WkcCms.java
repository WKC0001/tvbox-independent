package com.github.catvod.spider;

import android.content.Context;
import com.github.catvod.crawler.Spider;
import java.net.URI;
import java.util.*;
import org.json.*;

/** Dynamic CMS adapter. Every entry path checks current categories and metadata. */
public class WkcCms extends Spider {
    /** 上游在聚合里的序号，只用于"其它条件都相同时"的稳定排序。 */
    int order;
    protected JSONObject settings=new JSONObject();
    protected LinkedHashMap<String,String> types=new LinkedHashMap<>();
    protected String api="", provider="";
    private long checked;
    private final HashMap<String,String> defaults=new HashMap<>();
    /** 线路对外显示名。来源名必须出现在播放线路里——这是用户唯一能看到"这条线路是谁"的位置。 */
    protected String label(){String v=settings.optString("label","");return v.isEmpty()?provider:v;}
    /** 提示加在站点名里（见构建端 NOTICE），这里只在还没有的时候补一次，避免出现两遍。 */
    protected String display(){String name=label();return name.contains(WkcHome.NOTICE)?name:name+" "+WkcHome.NOTICE;}
    /** clean=抽帧 OCR 扫过且没发现博彩广告；flagged=扫到了；pending=没扫过（不能当成干净）。 */
    int adRank(){String v=settings.optString("ad_scan","pending");return "clean".equals(v)?0:"flagged".equals(v)?2:1;}
    /** 接口延迟（毫秒）。没有实测数据时排到最后，而不是当成 0 插到最前面。 */
    int latency(){int v=settings.optInt("latency_ms",0);return v>0?v:Integer.MAX_VALUE;}
    /** 上游原始的线路标识（蓝光/标清/m3u8…）。去掉会破坏分行的分隔符，长度也要收住——
        播放器把这一串直接显示在选源列表里，太长会看不出是谁。 */
    static String lineTag(String raw){
        String s=raw.replaceAll("[\\$#]+"," ").trim();
        if(s.length()>16)s=s.substring(0,16).trim();
        return s;
    }
    @Override public void init(Context context,String ext)throws Exception {
        settings=new JSONObject(ext);api=settings.getString("api");provider=settings.getString("id");
        if(!WkcNet.web(api))throw new IllegalArgumentException("Invalid provider API");
    }
    protected JSONObject request(String... args)throws Exception{return new JSONObject(WkcNet.get(WkcNet.query(api,args)));}
    protected synchronized void refresh()throws Exception {
        if(!types.isEmpty()&&System.currentTimeMillis()-checked<3600000)return;
        JSONObject response=request("ac","list","pg","1");JSONArray classes=response.getJSONArray("class");
        LinkedHashMap<String,String> fresh=new LinkedHashMap<>();
        for(int i=0;i<classes.length();i++){
            JSONObject c=classes.getJSONObject(i);String name=c.optString("type_name");
            if(WkcPolicy.genre(name)!=null)fresh.put(c.optString("type_id"),name);
        }
        if(fresh.isEmpty())throw new IllegalStateException("No approved categories");
        types=fresh;checked=System.currentTimeMillis();
    }
    protected boolean safe(JSONObject v){
        String tid=v.optString("type_id");
        if(!types.containsKey(tid)||v.optString("vod_id").isEmpty()||v.optString("vod_name").isEmpty())return false;
        String typeName=v.optString("type_name");
        if(!typeName.isEmpty()&&WkcPolicy.genre(typeName)==null)return false;
        return !WkcPolicy.blocked(v.optString("vod_name")+" "+typeName+" "+v.optString("vod_class")+" "+v.optString("vod_remarks")+" "+v.optString("vod_tag"));
    }
    /** 播放时的路线核对**刻意不做任何缓存**。
        试过把详情页刚取到的答复复用 60 秒（能省掉每集一次 0.5~1.6s 的往返），
        但那意味着"上游在这 60 秒内把内容改成违禁"时我们仍会放行——
        内容合规是硬闸门，不接受任何放行窗口，所以这里每次都拿实时详情去比。
        省时间只能省在"等待方式"上（见 WkcHome 的并发合并），不能省在"检查"上。 */

    protected JSONObject token(String original)throws Exception{return new JSONObject().put("provider",provider).put("id",original);}
    protected String original(String value)throws Exception {
        JSONObject t=WkcNet.unpack(value);
        if(!provider.equals(t.optString("provider")))throw new IllegalArgumentException("Wrong provider");
        return t.getString("id");
    }
    protected JSONObject filtered(JSONObject response)throws Exception {
        JSONArray list=response.optJSONArray("list"),out=new JSONArray();
        if(list!=null)for(int i=0;i<list.length();i++){
            JSONObject item=list.optJSONObject(i);if(item==null||!safe(item))continue;
            JSONObject v=new JSONObject(item.toString());v.put("vod_id",WkcNet.pack(token(v.get("vod_id").toString())));
            // Search and list responses must never expose unvalidated playable URLs.
            v.remove("vod_play_url");v.remove("vod_play_from");out.put(v);
        }
        JSONObject result=new JSONObject(response.toString());result.put("list",out);result.remove("class");return result;
    }
    protected JSONArray classes()throws Exception {
        JSONArray out=new JSONArray();
        for(String genre:WkcPolicy.GENRES){boolean exists=false;for(String name:types.values())if(genre.equals(WkcPolicy.genre(name)))exists=true;
            if(exists)out.put(new JSONObject().put("type_id",genre).put("type_name",genre));}
        return out;
    }
    @Override public String homeContent(boolean filter)throws Exception {
        refresh();JSONObject out=WkcNet.empty();out.put("class",classes());
        JSONObject filters=new JSONObject();
        for(String genre:WkcPolicy.GENRES){
            JSONArray choices=new JSONArray().put(new JSONObject().put("n","推荐").put("v",""));
            for(Map.Entry<String,String> e:types.entrySet())if(genre.equals(WkcPolicy.genre(e.getValue())))
                choices.put(new JSONObject().put("n",e.getValue()).put("v",e.getKey()));
            if(choices.length()>1)filters.put(genre,new JSONArray().put(new JSONObject().put("key","type").put("name","类型").put("value",choices)));
        }
        out.put("filters",filters);
        JSONObject recent=filtered(request("ac","detail","pg","1"));
        out.put("list",recent.getJSONArray("list"));return out.toString();
    }
    @Override public String homeVideoContent()throws Exception{refresh();return filtered(request("ac","detail","pg","1")).toString();}
    @Override public String categoryContent(String tid,String page,boolean filter,HashMap<String,String> extend)throws Exception {
        refresh();String target=extend==null?null:extend.get("type");
        if("".equals(target))target=null;
        if(target!=null&&!tid.equals(WkcPolicy.genre(types.getOrDefault(target,""))))return WkcNet.empty().toString();
        boolean explicit=target!=null;
        if(target==null)target=defaults.get(tid);
        // CMS parents often contain only uncategorized records instead of all child films.
        if(target==null)for(String preferred:new String[]{"国产剧","大陆剧","剧情片","动作片","大陆综艺","国产动漫","纪录片","短剧"}){
            for(Map.Entry<String,String> e:types.entrySet())if(preferred.equals(e.getValue())&&tid.equals(WkcPolicy.genre(preferred))){target=e.getKey();break;}
            if(target!=null)break;
        }
        if(target==null)for(Map.Entry<String,String> e:types.entrySet())if(tid.equals(e.getValue())){target=e.getKey();break;}
        if(target==null)for(Map.Entry<String,String> e:types.entrySet())if(tid.equals(WkcPolicy.genre(e.getValue()))){target=e.getKey();break;}
        if(target==null)return WkcNet.empty().toString();
        JSONObject response=filtered(request("ac","detail","t",target,"pg",page));
        if(response.getJSONArray("list").length()==0 && !explicit && !defaults.containsKey(tid)){
            for(Map.Entry<String,String> e:types.entrySet())if(!e.getKey().equals(target)&&tid.equals(WkcPolicy.genre(e.getValue()))){
                response=filtered(request("ac","detail","t",e.getKey(),"pg",page));
                if(response.getJSONArray("list").length()>0){target=e.getKey();break;}
            }
        }
        if(response.getJSONArray("list").length()>0&&!explicit)defaults.put(tid,target);
        return response.toString();
    }
    @Override public String searchContent(String word,boolean quick)throws Exception{return searchContent(word,quick,"1");}
    @Override public String searchContent(String word,boolean quick,String page)throws Exception {
        if(WkcPolicy.blocked(word))return WkcNet.empty().toString();
        refresh();return filtered(request("ac","detail","wd",word,"pg",page)).toString();
    }
    protected JSONObject detail(String id)throws Exception {
        refresh();JSONArray list=request("ac","detail","ids",id).optJSONArray("list");
        if(list!=null)for(int i=0;i<list.length();i++){
            JSONObject v=list.getJSONObject(i);
            if(id.equals(v.optString("vod_id"))&&safe(v))return v;
        }
        throw new IllegalStateException("Item unavailable or blocked by content policy");
    }
    protected boolean mediaAllowed(String value,String flag){
        try {
            if(!WkcNet.web(value))return false;
            URI u=new URI(value);String path=u.getPath().toLowerCase(Locale.ROOT);
            return WkcNet.contains(settings.getJSONArray("media_hosts"),u.getHost()) &&
                (path.endsWith(".m3u8")||path.endsWith(".mp4")||flag.toLowerCase(Locale.ROOT).contains("m3u8"));
        }catch(Exception e){return false;}
    }
    @Override public String detailContent(List<String> ids)throws Exception {
        if(ids.isEmpty())return WkcNet.empty().toString();
        String id=original(ids.get(0));JSONObject v=detail(id);
        String[] flags=v.optString("vod_play_from").split("\\$\\$\\$",-1),lines=v.optString("vod_play_url").split("\\$\\$\\$",-1);
        ArrayList<String> approvedFlags=new ArrayList<>(),approvedLines=new ArrayList<>();
        // 对外暴露的是"来源名 + 广告提示 + 上游原始线路名"，上游原始 flag 另存进 token 供播放时校验。
        // 不能直接只写 display()：同一个上游的蓝光/标清两条线路会塌成同一个名字，
        // 客户端去重后变成「飘零·2」「飘零·3」，用户看不出区别（实测截图里就是这样）。
        // 也不能直接改上游 flag 本身：playerContent 会用当前详情重新核对它。
        for(int i=0;i<Math.min(flags.length,lines.length);i++){
            String tag=lineTag(flags[i]);
            String shown=tag.isEmpty()?display():display()+" · "+tag;
            ArrayList<String> eps=new ArrayList<>();
            for(String ep:lines[i].split("#")){
                String[] pair=ep.split("\\$",2);if(pair.length!=2||!mediaAllowed(pair[1],flags[i]))continue;
                JSONObject t=token(id).put("flag",shown).put("raw",flags[i]).put("url",pair[1]);
                eps.add(pair[0]+"$"+WkcNet.pack(t));
            }
            if(!eps.isEmpty()){approvedFlags.add(shown);approvedLines.add(join(eps,"#"));}
        }
        v.put("vod_id",ids.get(0)).put("vod_play_from",join(approvedFlags,"$$$")).put("vod_play_url",join(approvedLines,"$$$"));
        return new JSONObject().put("list",new JSONArray().put(v)).toString();
    }
    @Override public String playerContent(String flag,String value,List<String> flags)throws Exception {
        JSONObject t=WkcNet.unpack(value);String id=original(value),url=t.getString("url");
        // flag 是对外显示名（含来源名/广告提示），可能被上层去重改写过，
        // 所以对上游的核对一律使用 token 里记着的原始 flag。
        String raw=t.optString("raw",flag);
        // 这两项每次都实时校验，不进缓存：域名白名单决定"这条 url 是谁家的"，
        // 后缀/flag 决定它确实是视频而不是网页。缓存里只有"上游答复"这一份数据。
        if(!flag.equals(t.getString("flag"))||!mediaAllowed(url,raw))throw new IllegalArgumentException("Unapproved playback route");
        JSONObject v=detail(id);String[] fs=v.optString("vod_play_from").split("\\$\\$\\$",-1),ls=v.optString("vod_play_url").split("\\$\\$\\$",-1);
        for(int i=0;i<Math.min(fs.length,ls.length);i++)if(raw.equals(fs[i]))for(String ep:ls[i].split("#")){
            String[] pair=ep.split("\\$",2);if(pair.length==2&&url.equals(pair[1]))
                return new JSONObject().put("parse",0).put("url",url).put("header",new JSONObject().put("User-Agent","okhttp/4.12.0")).toString();
        }
        throw new IllegalStateException("Playback route changed or removed");
    }
    static String join(List<String> a,String separator){StringBuilder b=new StringBuilder();for(String s:a){if(b.length()>0)b.append(separator);b.append(s);}return b.toString();}
}
