package com.github.catvod.spider;
import java.util.Map;import java.io.ByteArrayInputStream;
public class Proxy {public static Object[] proxy(Map<String,String> params){return new Object[]{404,"text/plain",new ByteArrayInputStream(new byte[0])};}}
