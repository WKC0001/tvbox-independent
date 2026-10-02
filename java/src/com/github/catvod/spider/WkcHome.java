package com.github.catvod.spider;
import android.content.Context;
import com.github.catvod.crawler.Spider;
import org.json.*;
import java.io.*;import java.net.*;import java.text.Normalizer;import java.util.*;
import java.util.concurrent.*;

/** Owned homepage adapter. It uses the same public CMS APIs as the independent native sites. */
public class WkcHome extends Spider {
 private static final String[] CATEGORIES={"电视剧","电影","综艺","动漫","纪录片","短剧"};
 private JSONArray sources=new JSONArray();
 private final ExecutorService pool=Executors.newFixedThreadPool(3);
 private final ConcurrentHashMap<String,Long> cooldown=new ConcurrentHashMap<String,Long>();
 private final ConcurrentHashMap<String,String> cache=new ConcurrentHashMap<String,String>();
 private final ConcurrentHashMap<String,Long> times=new ConcurrentHashMap<String,Long>();
 @Override public void init(Context context,String ext) throws Exception {sources=new JSONObject(ext).getJSONArray("sources");}
 private JSONObject read(JSONObject source,String params) throws Exception {
  String api=source.getString("api"),url=api+(api.contains("?")?"&":"?")+params;
  if(!url.startsWith("http://")&&!url.startsWith("https://"))throw new IOException("Unsupported URL");
  HttpURLConnection c=(HttpURLConnection)new URL(url).openConnection();
  c.setConnectTimeout(3500);c.setReadTimeout(4500);c.setRequestProperty("User-Agent","okhttp/4.12.0");
  try {
   if(c.getResponseCode()!=200)throw new IOException("CMS HTTP "+c.getResponseCode());
   ByteArrayOutputStream out=new ByteArrayOutputStream(); byte[] b=new byte[8192];
   try(InputStream in=c.getInputStream()){int n;while((n=in.read(b))!=-1){out.write(b,0,n);if(out.size()>6*1024*1024)throw new IOException("CMS response too large");}}
   return new JSONObject(new String(out.toByteArray(),"UTF-8"));
  } finally {c.disconnect();}
 }
 private static String encode(String s) throws Exception{return URLEncoder.encode(s,"UTF-8");}
 private static String identity(JSONObject v){
  // Keep year, season and sequel numbers so similarly titled releases remain distinct.
  return Normalizer.normalize(v.optString("vod_name"),Normalizer.Form.NFKC).replaceAll("[\\s\\p{Punct}]+","").toLowerCase(Locale.ROOT)+"|"+v.optString("vod_year");
 }
 private JSONObject adapt(JSONObject v,JSONObject s) throws Exception {
  JSONObject x=new JSONObject(v.toString());x.put("vod_id",s.getString("key")+"~"+encode(v.get("vod_id").toString()));
  if(x.optString("vod_remarks").isEmpty())x.put("vod_remarks",s.optString("name"));return x;
 }
 private JSONArray merge(List<JSONArray> lists) throws Exception {
  JSONArray result=new JSONArray();Set<String> seen=new HashSet<String>();
  // Interleave sources in priority order; prevent one large provider from filling the whole homepage.
  for(int n=0;n<24;n++)for(JSONArray list:lists)if(n<list.length()){
   JSONObject v=list.getJSONObject(n);if(!v.optString("vod_name").isEmpty()&&seen.add(identity(v)))result.put(v);
   if(result.length()>=48)return result;
  }return result;
 }
 private JSONObject listResult(JSONArray list,int page,int pageCount) throws Exception {
  return new JSONObject().put("list",list).put("page",page).put("pagecount",Math.max(page,pageCount)).put("limit",48).put("total",Math.max(list.length(),pageCount*48));
 }
 private String aggregate(final String category,final int page,final String word) throws Exception {
  return aggregate(category,page,word,0);
 }
 private String aggregate(final String category,final int page,final String word,int retry) throws Exception {
  String ck=category+"|"+page+"|"+word;long now=System.currentTimeMillis();
  Long time=times.get(ck);if(time!=null&&now-time<120000)return cache.get(ck);
  List<Future<JSONObject>> tasks=new ArrayList<Future<JSONObject>>();
  int count=0;
  for(int i=0;i<sources.length()&&count<3;i++){
   final JSONObject s=sources.getJSONObject(i);String key=s.getString("key");
   Long until=cooldown.get(key);if(until!=null&&until>now)continue;
   JSONArray ids=s.optJSONObject("categories").optJSONArray(category);
   if(!category.isEmpty()&&(ids==null||ids.length()==0))continue;
   final JSONArray categoryIds=ids;count++;
   tasks.add(pool.submit(new Callable<JSONObject>(){public JSONObject call() throws Exception {
    try {
     String params="ac=detail&pg="+page;
     if(!word.isEmpty())params+="&wd="+encode(word);
     if(!category.isEmpty()){
      // Rotate subcategories by page, while keeping each request a valid CMS page.
      String t=categoryIds.getString((page-1)%categoryIds.length());
      params="ac=detail&pg="+((page-1)/categoryIds.length()+1)+"&t="+encode(t);
     }
     JSONObject response=read(s,params);JSONArray raw=response.getJSONArray("list"),list=new JSONArray();
     for(int k=0;k<raw.length();k++){JSONObject v=raw.getJSONObject(k);
      if(!v.optString("type_name").matches(".*(?:伦理|倫理|成人|色情|预告|預告|擦边|擦邊).*"))list.put(adapt(v,s));
     }
     return new JSONObject().put("list",list).put("pagecount",response.optInt("pagecount",page)*(categoryIds==null?1:Math.max(1,categoryIds.length())));
    }catch(Exception e){cooldown.put(s.getString("key"),System.currentTimeMillis()+60000);throw e;}
   }}));
  }
  List<JSONArray> results=new ArrayList<JSONArray>();int pages=page;long deadline=System.currentTimeMillis()+9000;
  for(Future<JSONObject> task:tasks){
   try {JSONObject r=task.get(Math.max(1,deadline-System.currentTimeMillis()),TimeUnit.MILLISECONDS);results.add(r.getJSONArray("list"));pages=Math.max(pages,r.optInt("pagecount",page));}
   catch(Exception e){task.cancel(true);}
  }
  JSONArray list=merge(results);
  if(list.length()==0){String stale=cache.get(ck);if(stale!=null)return stale;
   if(retry==0&&results.isEmpty()&&sources.length()>3)return aggregate(category,page,word,1);
  }
  String result=listResult(list,page,pages).toString();
  if(list.length()>0){cache.put(ck,result);times.put(ck,now);}
  if(cache.size()>80){cache.clear();times.clear();}return result;
 }
 @Override public String homeContent(boolean filter) throws Exception {
  JSONArray classes=new JSONArray();for(String k:CATEGORIES)classes.put(new JSONObject().put("type_id",k).put("type_name",k));
  JSONObject home=new JSONObject(aggregate("",1,""));home.put("class",classes);return home.toString();
 }
 @Override public String homeVideoContent() throws Exception{return aggregate("",1,"");}
 @Override public String categoryContent(String tid,String pg,boolean filter,HashMap<String,String> extend) throws Exception {
  if(!Arrays.asList(CATEGORIES).contains(tid))return listResult(new JSONArray(),1,1).toString();
  int page=1;try{page=Math.max(1,Integer.parseInt(pg));}catch(Exception ignored){}
  return aggregate(tid,page,"");
 }
 @Override public String searchContent(String word,boolean quick) throws Exception{return aggregate("",1,word);}
 @Override public String searchContent(String word,boolean quick,String pg) throws Exception {
  int page=1;try{page=Math.max(1,Integer.parseInt(pg));}catch(Exception ignored){}return aggregate("",page,word);
 }
 @Override public String detailContent(List<String> ids) throws Exception {
  JSONArray result=new JSONArray();
  for(String id:ids){int at=id.indexOf('~');if(at<1)continue;String key=id.substring(0,at),raw=URLDecoder.decode(id.substring(at+1),"UTF-8");
   for(int i=0;i<sources.length();i++){JSONObject s=sources.getJSONObject(i);if(!s.getString("key").equals(key))continue;
    JSONObject response=read(s,"ac=detail&ids="+encode(raw));JSONArray videos=response.getJSONArray("list");
    for(int k=0;k<videos.length();k++){
     JSONObject v=adapt(videos.getJSONObject(k),s);
     String[] flags=v.optString("vod_play_from").split("\\$\\$\\$"),lines=v.optString("vod_play_url").split("\\$\\$\\$");
     List<String> fs=new ArrayList<String>(),ls=new ArrayList<String>();
     for(int n=0;n<Math.min(flags.length,lines.length);n++)if(flags[n].toLowerCase(Locale.ROOT).contains("m3u8")||lines[n].split("#")[0].matches(".*\\.m3u8(?:[?].*)?")){fs.add(flags[n]);ls.add(lines[n]);}
     v.put("vod_play_from",join(fs,"$$$")).put("vod_play_url",join(ls,"$$$"));result.put(v);
    }break;
   }
  }return new JSONObject().put("list",result).toString();
 }
 private static String join(List<String> items,String sep){StringBuilder b=new StringBuilder();for(String s:items){if(b.length()>0)b.append(sep);b.append(s);}return b.toString();}
 @Override public String playerContent(String flag,String id,List<String> vip) throws Exception {
  if(!id.startsWith("http://")&&!id.startsWith("https://"))throw new IOException("Unsupported play URL");
  return new JSONObject().put("parse",0).put("url",id).put("header",new JSONObject().put("User-Agent","okhttp/4.12.0")).toString();
 }
 @Override public void destroy(){pool.shutdownNow();cache.clear();times.clear();}
}
