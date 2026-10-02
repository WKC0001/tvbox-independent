import com.github.catvod.spider.WkcHome;import org.json.*;import java.nio.file.*;import java.util.*;
public class HomeIntegration {
 public static void main(String[] a)throws Exception {
  JSONObject config=new JSONObject(new String(Files.readAllBytes(Paths.get("api.json")),"UTF-8"));
  WkcHome s=new WkcHome();s.init(null,config.getJSONArray("sites").getJSONObject(0).getJSONObject("ext").toString());
  try{
   JSONObject h=new JSONObject(s.homeContent(false));JSONArray list=h.getJSONArray("list");
   if(list.length()==0||h.getJSONArray("class").length()!=6)throw new Exception("Homepage empty / categories missing");
   int posters=0;for(int i=0;i<list.length();i++)if(!list.getJSONObject(i).optString("vod_pic").isEmpty())posters++;
   JSONObject d=new JSONObject(s.detailContent(Arrays.asList(list.getJSONObject(0).getString("vod_id"))));
   if(d.getJSONArray("list").length()==0||d.getJSONArray("list").getJSONObject(0).optString("vod_play_url").isEmpty())throw new Exception("Homepage detail routing failed");
   JSONObject c=new JSONObject(s.categoryContent("电影","1",false,new HashMap<String,String>()));
   if(c.getJSONArray("list").length()==0)throw new Exception("Movie category empty");
   JSONObject result=new JSONObject().put("home_videos",list.length()).put("posters",posters).put("categories",6).put("movie_videos",c.getJSONArray("list").length()).put("detail_routing",true).put("device_test",false);
   Files.write(Paths.get("home-integration.json"),result.toString(2).getBytes("UTF-8"));System.out.println(result);
  }finally{s.destroy();}
 }
}
