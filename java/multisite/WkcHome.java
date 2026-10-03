package com.github.catvod.spider;

import android.content.Context;
import com.github.catvod.crawler.Spider;
import java.util.*;
import org.json.*;

/** Owned dynamic home: fallback between approved providers, stable provider-aware ids. */
public class WkcHome extends Spider {
    protected final ArrayList<WkcCms> providers=new ArrayList<>();
    @Override public void init(Context c,String ext)throws Exception {
        JSONArray sources=new JSONObject(ext).getJSONArray("providers");providers.clear();
        for(int i=0;i<sources.length();i++){WkcCms s=new WkcCms();s.init(c,sources.getJSONObject(i).toString());providers.add(s);}
        if(providers.isEmpty())throw new IllegalStateException("No approved home provider");
    }
    private WkcCms owner(String id)throws Exception{
        String provider=WkcNet.unpack(id).getString("provider");
        for(WkcCms s:providers)if(s.provider.equals(provider))return s;
        throw new IllegalArgumentException("Unknown provider");
    }
    @Override public String homeContent(boolean f)throws Exception {
        Exception failure=null;
        for(WkcCms s:providers)try{
            JSONObject out=new JSONObject(s.homeContent(f));
            if(out.getJSONArray("list").length()==0)continue;
            // Subtype ids differ between providers; expose names so fallback can translate them.
            JSONObject filters=out.optJSONObject("filters");
            if(filters!=null)for(String key:filters.keySet()){
                JSONArray groups=filters.getJSONArray(key);
                for(int i=0;i<groups.length();i++){
                    JSONObject group=groups.getJSONObject(i);group.put("key","type_name");
                    JSONArray values=group.getJSONArray("value");
                    for(int j=0;j<values.length();j++){JSONObject v=values.getJSONObject(j);if(!v.optString("v").isEmpty())v.put("v",v.getString("n"));}
                }
            }
            return out.toString();
        }catch(Exception e){failure=e;}
        if(failure!=null)throw failure;return WkcNet.empty().toString();
    }
    @Override public String homeVideoContent()throws Exception{return homeContent(false);}
    @Override public String categoryContent(String t,String p,boolean f,HashMap<String,String> e)throws Exception{
        Exception failure=null;
        for(WkcCms s:providers)try{
            HashMap<String,String> mapped=e==null?new HashMap<>():new HashMap<>(e);
            String name=mapped.remove("type_name");mapped.remove("type");
            if(name!=null&&!name.isEmpty()){
                s.refresh();String id=null;
                for(Map.Entry<String,String> entry:s.types.entrySet())if(name.equals(entry.getValue())){id=entry.getKey();break;}
                if(id==null)continue;mapped.put("type",id);
            }
            String out=s.categoryContent(t,p,f,mapped);if(new JSONObject(out).getJSONArray("list").length()>0)return out;
        }catch(Exception ex){failure=ex;}
        if(failure!=null)throw failure;return WkcNet.empty().toString();
    }
    @Override public String searchContent(String w,boolean q)throws Exception{return searchContent(w,q,"1");}
    @Override public String searchContent(String w,boolean q,String page)throws Exception{
        Exception failure=null;
        for(WkcCms s:providers)try{String out=s.searchContent(w,q,page);if(new JSONObject(out).getJSONArray("list").length()>0)return out;}catch(Exception e){failure=e;}
        if(failure!=null)throw failure;return WkcNet.empty().toString();
    }
    @Override public String detailContent(List<String> ids)throws Exception{return owner(ids.get(0)).detailContent(ids);}
    @Override public String playerContent(String f,String id,List<String> v)throws Exception{return owner(id).playerContent(f,id,v);}
}
