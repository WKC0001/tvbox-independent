import com.github.catvod.spider.WkcHome;import org.json.*;import java.nio.file.*;import java.util.*;
public class HomeIntegration {
 public static void main(String[] a)throws Exception {
  JSONObject api=new JSONObject(new String(Files.readAllBytes(Paths.get("api.json")),"UTF-8"));WkcHome s=new WkcHome();
  try{s.init(null,api.getJSONArray("sites").getJSONObject(0).getJSONObject("ext").toString());JSONObject home=new JSONObject(s.homeContent(false));
   int posters=0;JSONArray list=home.getJSONArray("list");for(int i=0;i<list.length();i++)if(!list.getJSONObject(i).optString("vod_pic").isEmpty())posters++;
   JSONObject result=new JSONObject().put("home_videos",list.length()).put("posters",posters).put("categories",home.getJSONArray("class")).put("reviewed_only",true).put("external_cms_runtime",false).put("device_test",false);
   Files.write(Paths.get("home-integration.json"),result.toString(2).getBytes("UTF-8"));System.out.println(result);
  }finally{s.destroy();}
 }
}
