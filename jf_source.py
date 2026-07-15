#!/usr/bin/env python3
import json, os, subprocess, sys, urllib.request
CONF="/opt/writ-fm/jellyfin.conf"; PLAYLIST="/opt/writ-fm/music_playlist.txt"; STATE="/opt/writ-fm/current_source.txt"
def cfg():
    c={}
    for l in open(CONF):
        l=l.strip()
        if "=" in l and not l.startswith("#"):
            k,v=l.split("=",1); c[k]=v
    return c
def auth():
    c=cfg(); body=json.dumps({"Username":c["JELLYFIN_USER"],"Pw":c["JELLYFIN_PASS"]}).encode()
    req=urllib.request.Request(c["JELLYFIN_URL"]+"/Users/AuthenticateByName",data=body,
        headers={"Content-Type":"application/json","X-Emby-Authorization":'MediaBrowser Client="te-radio", Device="te-radio", DeviceId="te-radio-38", Version="1.0"'})
    r=json.loads(urllib.request.urlopen(req,timeout=10).read()); return c["JELLYFIN_URL"], r["AccessToken"], r["User"]["Id"]
def jget(base,tok,path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(base+path,headers={"X-Emby-Token":tok}),timeout=25).read())
def sources():
    base,tok,uid=auth(); out=[]; views=jget(base,tok,"/Users/%s/Views"%uid)
    mid=next((v["Id"] for v in views.get("Items",[]) if v.get("CollectionType")=="music"),None)
    if mid: out.append({"id":"library:"+mid,"name":"Music Library (shuffle)"})
    pls=jget(base,tok,"/Users/%s/Items?IncludeItemTypes=Playlist&Recursive=true"%uid)
    for p in pls.get("Items",[]): out.append({"id":"playlist:"+p["Id"],"name":"Playlist: "+p["Name"]})
    cur=open(STATE).read().strip() if os.path.exists(STATE) else ""
    return {"sources":out,"current":cur}
def set_source(src):
    base,tok,uid=auth(); kind,sid=src.split(":",1)
    if kind=="library": items=jget(base,tok,"/Users/%s/Items?ParentId=%s&IncludeItemTypes=Audio&Recursive=true&SortBy=Random&Limit=500"%(uid,sid))
    else: items=jget(base,tok,"/Playlists/%s/Items?UserId=%s&Limit=1000"%(sid,uid))
    ids=[i["Id"] for i in items.get("Items",[])]
    with open(PLAYLIST,"w") as f:
        for i in ids: f.write("file '%s/Audio/%s/stream.mp3?api_key=%s&audioBitRate=128000'\n"%(base,i,tok))
    subprocess.run(["systemctl","restart","writ-stream.service"],capture_output=True); open(STATE,"w").write(src)
    return {"ok":True,"tracks":len(ids)}
if __name__=="__main__":
    cmd=sys.argv[1] if len(sys.argv)>1 else "list"
    try: print(json.dumps(sources() if cmd=="list" else set_source(sys.argv[2])))
    except Exception as e: print(json.dumps({"error":str(e)}))
