package com.github.catvod.spider;
import android.content.Context;import com.github.catvod.crawler.Spider;import org.json.*;
import java.util.*;import java.text.Normalizer;import java.security.MessageDigest;import java.io.IOException;
/** Reviewed, immutable local catalogue. No upstream CMS browsing or search is exposed. */
public class WkcHome extends Spider {
 private JSONArray catalog=new JSONArray();private String provider="";
 private final Map<String,JSONObject> records=new LinkedHashMap<String,JSONObject>();
 private final Set<String> allowedUrls=new HashSet<String>();
 private static final String[] CATS={"电影","电视剧","综艺","动漫","纪录片","少儿"};
 private static String norm(String s){return Normalizer.normalize(s,Normalizer.Form.NFKC).replaceAll("[\\s\\p{Punct}]+","").toLowerCase(Locale.ROOT);}
 private static String digest(String s)throws Exception {byte[] b=MessageDigest.getInstance("SHA-256").digest(s.getBytes("UTF-8"));StringBuilder h=new StringBuilder();for(byte n:b)h.append(String.format(Locale.ROOT,"%02x",n&255));return h.toString();}
 @Override public void init(Context c,String ext)throws Exception {
  records.clear();allowedUrls.clear();JSONObject config=new JSONObject(ext);String data=config.getString("catalog_json");
  if(!digest(data).equals(ApprovedCatalogue.SHA256))throw new IOException("Catalogue has not passed this release's review");
  provider=config.optString("provider");catalog=new JSONArray(data);
  for(int i=0;i<catalog.length();i++){
   JSONObject original=catalog.getJSONObject(i),v=new JSONObject(original.toString());
   if(!v.optBoolean("approved")||!Arrays.asList(CATS).contains(v.optString("category")))continue;
   String[] fs=v.getString("vod_play_from").split("\\$\\$\\$"),ls=v.getString("vod_play_url").split("\\$\\$\\$");List<String> flags=new ArrayList<String>(),lines=new ArrayList<String>();
   for(int n=0;n<Math.min(fs.length,ls.length);n++)if(provider.isEmpty()||fs[n].equals(provider)){
    flags.add(fs[n]);lines.add(ls[n]);for(String ep:ls[n].split("#")){int at=ep.indexOf('$');if(at>0)allowedUrls.add(ep.substring(at+1));}
   }
   if(lines.isEmpty())continue;v.put("vod_play_from",join(flags,"$$$")).put("vod_play_url",join(lines,"$$$"));records.put(v.getString("vod_id"),v);
  }
 }
 private static String join(List<String> a,String sep){StringBuilder b=new StringBuilder();for(String s:a){if(b.length()>0)b.append(sep);b.append(s);}return b.toString();}
 private String result(List<JSONObject> items,int page)throws Exception {
  int limit=24,total=items.size(),pages=Math.max(1,(total+limit-1)/limit);JSONArray list=new JSONArray();
  for(int i=(page-1)*limit;i<Math.min(total,page*limit);i++)list.put(items.get(i));
  return new JSONObject().put("list",list).put("page",page).put("pagecount",pages).put("limit",limit).put("total",total).toString();
 }
 @Override public String homeContent(boolean filter)throws Exception {
  JSONObject o=new JSONObject(result(new ArrayList<JSONObject>(records.values()),1));JSONArray classes=new JSONArray();
  for(String cat:CATS){for(JSONObject v:records.values())if(cat.equals(v.optString("category"))){classes.put(new JSONObject().put("type_id",cat).put("type_name",cat));break;}}
  return o.put("class",classes).toString();
 }
 @Override public String homeVideoContent()throws Exception{return result(new ArrayList<JSONObject>(records.values()),1);}
 @Override public String categoryContent(String tid,String pg,boolean filter,HashMap<String,String> extend)throws Exception {
  List<JSONObject> list=new ArrayList<JSONObject>();for(JSONObject v:records.values())if(tid.equals(v.optString("category")))list.add(v);return result(list,page(pg));
 }
 private static int page(String s){try{return Math.max(1,Integer.parseInt(s));}catch(Exception e){return 1;}}
 @Override public String searchContent(String w,boolean q)throws Exception{return searchContent(w,q,"1");}
 @Override public String searchContent(String w,boolean q,String pg)throws Exception {
  List<JSONObject> list=new ArrayList<JSONObject>();String word=norm(w);
  if(!word.isEmpty())for(JSONObject v:records.values())if(norm(v.getString("vod_name")).contains(word))list.add(v);
  return result(list,page(pg));
 }
 @Override public String detailContent(List<String> ids)throws Exception {
  JSONArray list=new JSONArray();for(String id:ids){JSONObject v=records.get(id);if(v!=null)list.put(v);}return new JSONObject().put("list",list).toString();
 }
 @Override public String playerContent(String flag,String id,List<String> vip)throws Exception {
  if(!allowedUrls.contains(id))throw new IOException("Unreviewed play URL rejected");
  return new JSONObject().put("parse",0).put("url",id).put("header",new JSONObject().put("User-Agent","okhttp/4.12.0")).toString();
 }
 @Override public void destroy(){records.clear();allowedUrls.clear();catalog=new JSONArray();}
}
