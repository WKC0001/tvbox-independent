import com.github.catvod.spider.WkcHome;import com.sun.net.httpserver.*;import java.net.*;import java.util.*;import org.json.*;
public class HomeTest{
 static void check(boolean v,String m){if(!v)throw new AssertionError(m);}
 public static void main(String[] a)throws Exception{
  HttpServer server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
  server.createContext("/bad",e->{e.sendResponseHeaders(503,-1);e.close();});
  server.createContext("/good",e->{try{
   String q=e.getRequestURI().getRawQuery();JSONArray vs=new JSONArray();
   if(!q.contains("wd=NO_MATCH"))for(int i=0;i<3;i++)vs.put(new JSONObject().put("vod_id",i+1).put("vod_name",i==2?"测试剧第二季":"测试剧").put("vod_year",i==1?"2024":"2026").put("vod_pic","https://example.com/poster.jpg").put("vod_play_from","web$$$testm3u8").put("vod_play_url","网页$https://example.com/page$$$第1集$https://example.com/test.m3u8"));
   byte[] b=new JSONObject().put("list",vs).put("pagecount",5).put("page",1).toString().getBytes("UTF-8");e.sendResponseHeaders(200,b.length);e.getResponseBody().write(b);e.close();
  }catch(Exception ex){throw new RuntimeException(ex);}});server.start();WkcHome s=new WkcHome();
  try{
   JSONArray sources=new JSONArray();for(int i=0;i<3;i++){JSONObject cats=new JSONObject();for(String k:new String[]{"电视剧","电影","综艺","动漫","纪录片","短剧"})cats.put(k,new JSONArray().put("1"));sources.put(new JSONObject().put("key","s"+i).put("name","source"+i).put("api","http://127.0.0.1:"+server.getAddress().getPort()+(i==0?"/bad":"/good")).put("categories",cats));}
   s.init(null,new JSONObject().put("sources",sources).toString());JSONObject h=new JSONObject(s.homeContent(false));
   check(h.getJSONArray("class").length()==6,"six categories");check(h.getJSONArray("list").length()==3,"outage failover, dedup and preserve year/season");
   String id=h.getJSONArray("list").getJSONObject(0).getString("vod_id");check(id.startsWith("s1~"),"provider routed ID");
   JSONObject d=new JSONObject(s.detailContent(Arrays.asList(id))).getJSONArray("list").getJSONObject(0);check(d.getString("vod_play_from").equals("testm3u8"),"remove non-direct webpage line");
   JSONObject cat=new JSONObject(s.categoryContent("电视剧","2",false,new HashMap<String,String>()));check(cat.getInt("page")==2&&cat.getJSONArray("list").length()==3,"category paging");
   check(new JSONObject(s.searchContent("NO_MATCH",false)).getJSONArray("list").length()==0,"negative search");
   check(new JSONObject(s.playerContent("testm3u8","https://example.com/test.m3u8",new ArrayList<String>())).getInt("parse")==0,"direct playback");
   WkcHome fallback=new WkcHome();try{
    JSONArray failover=new JSONArray();for(int i=0;i<4;i++){JSONObject profile=new JSONObject(sources.getJSONObject(i==3?1:0).toString());profile.put("key","f"+i);failover.put(profile);}
    fallback.init(null,new JSONObject().put("sources",failover).toString());check(new JSONObject(fallback.homeContent(false)).getJSONArray("list").length()==3,"all first three down: retry next provider");
   }finally{fallback.destroy();}
   System.out.println("HOME_TESTS_PASSED: outage, dedup, seasons, routing, category paging, search, direct line");
  }finally{s.destroy();server.stop(0);}
 }
}
