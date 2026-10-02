#!/bin/bash
set -eu
cd "$(dirname "$0")"
mkdir -p classes dex
javac -encoding UTF-8 -source 8 -target 8 -cp json.jar -d classes stubs/android/content/Context.java stubs/com/github/catvod/crawler/Spider.java src/com/github/catvod/spider/*.java test/HomeTest.java
java -cp classes:json.jar HomeTest
jar cf home-classes.jar -C classes com/github/catvod/spider
java -cp "${D8_JAR:?D8_JAR required}" com.android.tools.r8.D8 --min-api 24 --no-desugaring --output dex home-classes.jar
jar cf ../home.jpg -C dex classes.dex
