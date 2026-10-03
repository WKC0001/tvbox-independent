package com.github.catvod.spider;

import android.content.Context;
import com.github.catvod.crawler.Spider;
import java.util.*;
import org.json.*;

/** Full-path policy wrapper around preserved native adapters. Unknown metadata fails closed. */
public class WkcNative extends Spider {
    private Spider delegate;
    private String provider;
    private final HashMap<String,String> types=new HashMap<>();
    private final HashMap<String,String> approvedItems=new HashMap<>();
    @Override public void init(Context c,String ext)throws Exception{
        JSONObject o=new JSONObject(ext);provider=o.getString("id");String name=o.getString("adapter");
        if(!Arrays.asList(WkcPolicy.NATIVE_CLASSES).contains(name))throw new IllegalArgumentException("Unregistered native adapter");
        delegate=Init.getSpider("com.github.catvod.spider."+name);
        Object inner=o.opt("original_ext");delegate.init(c,inner==null?"":inner.toString());
    }
    private void categories(JSONObject o)throws Exception{
        JSONArray a=o.optJSONArray("class");if(a==null)return;
        types.clear();JSONArray out=new JSONArray();
        for(int i=0;i<a.length();i++){
            JSONObject v=a.getJSONObject(i);String name=v.optString("type_name");
            if(WkcPolicy.genre(name)!=null){types.put(v.optString("type_id"),name);out.put(v);}
        }
        o.put("class",out);o.remove("filters");
    }
    private void ensureCategories()throws Exception{if(types.isEmpty())categories(new JSONObject(delegate.homeContent(false)));}
    private boolean safe(JSONObject v,String context){
        if(v.optString("vod_name").isEmpty()||WkcPolicy.blocked(v.optString("vod_name")+" "+v.optString("type_name")+" "+v.optString("vod_class")+" "+v.optString("vod_remarks")))return false;
        String tn=v.optString("type_name");
        if(!tn.isEmpty())return WkcPolicy.genre(tn)!=null;
        String tid=v.optString("type_id");
        if(!tid.isEmpty())return types.containsKey(tid);
        String tags=v.optString("vod_class");
        if(!tags.isEmpty()){
            boolean all=true;for(String tag:tags.split("[,，/ ]+"))if(WkcPolicy.genre(tag)==null)all=false;
            if(all)return true;
        }
        return context!=null&&types.containsKey(context);
    }
    private JSONObject token(String id)throws Exception{return new JSONObject().put("provider",provider).put("id",id);}
    private String original(String id)throws Exception{
        JSONObject t=WkcNet.unpack(id);if(!provider.equals(t.optString("provider")))throw new IllegalArgumentException("Wrong native provider");return t.getString("id");
    }
    private String filter(String json,String context)throws Exception{
        JSONObject o=new JSONObject(json);categories(o);JSONArray a=o.optJSONArray("list"),out=new JSONArray();
        int detailChecks=0;
        if(a!=null)for(int i=0;i<a.length();i++){
            JSONObject v=a.getJSONObject(i);
            if(!safe(v,context)&&context==null&&detailChecks<5&&!WkcPolicy.blocked(v.optString("vod_name"))){
                detailChecks++;
                try{JSONArray details=new JSONObject(delegate.detailContent(Collections.singletonList(v.optString("vod_id")))).optJSONArray("list");
                    if(details!=null&&details.length()>0&&safe(details.getJSONObject(0),null)){
                        JSONObject d=details.getJSONObject(0);v.put("type_name",d.optString("type_name")).put("vod_class",d.optString("vod_class"));
                        if(d.has("type_id"))v.put("type_id",d.get("type_id"));
                    }
                }catch(Exception ignored){}
            }
            if(!safe(v,context))continue;
            String id=v.optString("vod_id");if(id.isEmpty())continue;
            if(context!=null)approvedItems.put(id,context);
            v.put("vod_id",WkcNet.pack(token(id)));v.remove("vod_play_url");v.remove("vod_play_from");out.put(v);
        }
        o.put("list",out);return o.toString();
    }
    @Override public String homeContent(boolean f)throws Exception{return filter(delegate.homeContent(f),null);}
    @Override public String homeVideoContent()throws Exception{ensureCategories();return filter(delegate.homeVideoContent(),null);}
    @Override public String categoryContent(String t,String p,boolean f,HashMap<String,String> e)throws Exception{
        ensureCategories();if(!types.containsKey(t))return WkcNet.empty().toString();return filter(delegate.categoryContent(t,p,f,e),t);
    }
    @Override public String searchContent(String w,boolean q)throws Exception{
        if(WkcPolicy.blocked(w))return WkcNet.empty().toString();ensureCategories();
        return filter(delegate.searchContent(w,q),null);
    }
    @Override public String searchContent(String w,boolean q,String p)throws Exception{
        if("1".equals(p))return searchContent(w,q);
        if(WkcPolicy.blocked(w))return WkcNet.empty().toString();ensureCategories();return filter(delegate.searchContent(w,q,p),null);
    }
    private JSONObject detail(String id)throws Exception{
        ensureCategories();JSONArray list=new JSONObject(delegate.detailContent(Collections.singletonList(id))).optJSONArray("list");
        if(list!=null)for(int i=0;i<list.length();i++){
            JSONObject v=list.getJSONObject(i);if(id.equals(v.optString("vod_id"))&&safe(v,approvedItems.get(id)))return v;
        }
        throw new IllegalStateException("Unverified native item metadata");
    }
    @Override public String detailContent(List<String> ids)throws Exception{
        String id=original(ids.get(0));JSONObject v=detail(id);String[] fs=v.optString("vod_play_from").split("\\$\\$\\$",-1),ls=v.optString("vod_play_url").split("\\$\\$\\$",-1);
        ArrayList<String> flags=new ArrayList<>(),lines=new ArrayList<>();
        for(int i=0;i<Math.min(fs.length,ls.length);i++){
            ArrayList<String> eps=new ArrayList<>();for(String ep:ls[i].split("#")){
                String[] pair=ep.split("\\$",2);if(pair.length==2)eps.add(pair[0]+"$"+WkcNet.pack(token(id).put("flag",fs[i]).put("episode",pair[1])));
            }
            if(!eps.isEmpty()){flags.add(fs[i]);lines.add(WkcCms.join(eps,"#"));}
        }
        v.put("vod_id",ids.get(0)).put("vod_play_from",WkcCms.join(flags,"$$$")).put("vod_play_url",WkcCms.join(lines,"$$$"));
        return new JSONObject().put("list",new JSONArray().put(v)).toString();
    }
    @Override public String playerContent(String f,String packed,List<String> flags)throws Exception{
        JSONObject t=WkcNet.unpack(packed);String id=original(packed),ep=t.getString("episode");
        if(!f.equals(t.getString("flag")))throw new IllegalArgumentException("Wrong episode flag");
        JSONObject v=detail(id);String[] fs=v.optString("vod_play_from").split("\\$\\$\\$",-1),ls=v.optString("vod_play_url").split("\\$\\$\\$",-1);
        for(int i=0;i<Math.min(fs.length,ls.length);i++)if(f.equals(fs[i]))for(String item:ls[i].split("#")){
            String[] pair=item.split("\\$",2);if(pair.length==2&&ep.equals(pair[1]))return delegate.playerContent(f,ep,flags);
        }
        throw new IllegalStateException("Episode removed or blocked");
    }
    @Override public void destroy(){if(delegate!=null)delegate.destroy();approvedItems.clear();types.clear();}
}
