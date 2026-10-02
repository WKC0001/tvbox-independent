import com.github.catvod.spider.WkcHome;import org.json.*;import java.nio.file.*;import java.util.*;
public class HomeTest {
 static void check(boolean v,String s){if(!v)throw new AssertionError(s);}
 static String ext()throws Exception{return new JSONObject(new String(Files.readAllBytes(Paths.get("../api.json")),"UTF-8")).getJSONArray("sites").getJSONObject(0).getJSONObject("ext").toString();}
 public static void main(String[] args)throws Exception {
  WkcHome s=new WkcHome();try{
   s.init(null,ext());JSONObject h=new JSONObject(s.homeContent(false));JSONArray list=h.getJSONArray("list");check(list.length()>0,"reviewed catalogue available");
   String id=list.getJSONObject(0).getString("vod_id");check(new JSONObject(s.detailContent(Arrays.asList(id))).getJSONArray("list").length()==1,"approved detail");
   check(new JSONObject(s.detailContent(Arrays.asList("forged~adult-id"))).getJSONArray("list").length()==0,"forged detail blocked");
   for(String word:new String[]{"伦理","福利","色情","东京热","无码","传媒","低俗未知片名"})check(new JSONObject(s.searchContent(word,false)).getJSONArray("list").length()==0,"unreviewed search blocked");
   check(new JSONObject(s.categoryContent("伦理片","1",false,new HashMap<String,String>())).getJSONArray("list").length()==0,"unknown adult category blocked");
   boolean rejected=false;try{s.playerContent("m3u8","https://example.com/unreviewed.m3u8",new ArrayList<String>());}catch(Exception e){rejected=true;}check(rejected,"unreviewed media URL blocked");
   JSONObject tampered=new JSONObject(ext());tampered.put("catalog_json",tampered.getString("catalog_json")+" ");WkcHome other=new WkcHome();rejected=false;try{other.init(null,tampered.toString());}catch(Exception e){rejected=true;}check(rejected,"modified catalogue rejected");other.destroy();
   System.out.println("CONTENT_GATE_TESTS_PASSED: homepage/category/search/detail/player/tamper checks");
  }finally{s.destroy();}
 }
}
