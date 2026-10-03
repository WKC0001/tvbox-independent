package com.github.catvod.spider;
import com.github.catvod.crawler.Spider;
/** Host-only regression fixture, never included in the shipped DEX. */
public class Jpys extends Spider {
    public String homeContent(boolean f){return "{\"class\":[{\"type_id\":\"1\",\"type_name\":\"电影\"}],\"list\":[]}";}
    public String searchContent(String w,boolean q){return "{\"list\":[{\"vod_id\":\"1\",\"vod_name\":\"正常影片\",\"type_name\":\"动作片\"}]}";}
    public String searchContent(String w,boolean q,String page){throw new UnsupportedOperationException("Legacy adapter only implements two arguments");}
}
