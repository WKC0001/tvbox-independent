package com.github.catvod.spider;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.zip.GZIPInputStream;
import org.json.*;
import android.util.Base64;

final class WkcNet {
    static boolean web(String value) {
        try { URI u=new URI(value); return ("https".equals(u.getScheme())||"http".equals(u.getScheme())) && u.getHost()!=null && u.getUserInfo()==null; }
        catch(Exception e){return false;}
    }
    static String get(String value) throws Exception {
        for(int redirect=0;redirect<5;redirect++) {
            if(!web(value))throw new IOException("Invalid HTTP URL");
            HttpURLConnection c=(HttpURLConnection)new URL(value).openConnection();
            c.setConnectTimeout(8000);c.setReadTimeout(10000);c.setInstanceFollowRedirects(false);
            c.setRequestProperty("User-Agent","okhttp/4.12.0");c.setRequestProperty("Accept-Encoding","gzip");
            try {
                int code=c.getResponseCode();
                if(code>=300&&code<400){value=new URL(new URL(value),c.getHeaderField("Location")).toString();continue;}
                if(code!=200)throw new IOException("Upstream HTTP "+code);
                InputStream raw=c.getInputStream();
                try(InputStream in="gzip".equalsIgnoreCase(c.getContentEncoding())?new GZIPInputStream(raw):raw;
                    ByteArrayOutputStream out=new ByteArrayOutputStream()) {
                    byte[] b=new byte[8192];int n;
                    while((n=in.read(b))!=-1){out.write(b,0,n);if(out.size()>8000000)throw new IOException("Response too large");}
                    return new String(out.toByteArray(),StandardCharsets.UTF_8);
                }
            } finally {c.disconnect();}
        }
        throw new IOException("Redirect limit");
    }
    static String query(String url, String... values) throws Exception {
        URI u=new URI(url);LinkedHashMap<String,String> q=new LinkedHashMap<>();
        if(u.getRawQuery()!=null)for(String part:u.getRawQuery().split("&")){
            String[] kv=part.split("=",2);q.put(URLDecoder.decode(kv[0],"UTF-8"),kv.length==2?URLDecoder.decode(kv[1],"UTF-8"):"");
        }
        for(int i=0;i<values.length;i+=2)q.put(values[i],values[i+1]);
        StringBuilder b=new StringBuilder(url.split("[?#]",2)[0]);b.append('?');
        for(Map.Entry<String,String> e:q.entrySet())b.append(URLEncoder.encode(e.getKey(),"UTF-8")).append('=').append(URLEncoder.encode(e.getValue(),"UTF-8")).append('&');
        return b.toString();
    }
    static String pack(JSONObject value){return "wkc:"+Base64.encodeToString(value.toString().getBytes(StandardCharsets.UTF_8),Base64.URL_SAFE|Base64.NO_WRAP|Base64.NO_PADDING);}
    static JSONObject unpack(String value)throws Exception{
        if(!value.startsWith("wkc:"))throw new IllegalArgumentException("Unreviewed item id");
        return new JSONObject(new String(Base64.decode(value.substring(4),Base64.URL_SAFE|Base64.NO_WRAP),StandardCharsets.UTF_8));
    }
    static JSONObject empty()throws Exception{return new JSONObject().put("list",new JSONArray()).put("page",1).put("pagecount",1).put("limit",20).put("total",0);}
    static boolean contains(JSONArray a,String s){for(int i=0;i<a.length();i++)if(s.equals(a.optString(i)))return true;return false;}
}
