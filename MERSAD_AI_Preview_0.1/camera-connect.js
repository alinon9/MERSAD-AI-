/* MERSAD unified camera onboarding */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  async function readJson(response, fallbackMessage) {
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
      throw new Error(data.error || (fallbackMessage + " (HTTP " + response.status + ")"));
    }
    return data;
  }
  function init() {
    const bar = $("cam-sw");
    if (!bar || $("mc-open")) return;
    const open = document.createElement("button");
    open.id = "mc-open"; open.type = "button"; open.className = "ok";
    open.textContent = "＋ ربط كاميرا";
    bar.parentNode.insertBefore(open, bar.nextSibling);
    const panel = document.createElement("div");
    panel.id = "mc-panel";
    panel.style.cssText = "position:fixed;inset:0;background:#000b;z-index:1000;display:none;align-items:center;justify-content:center;padding:14px";
    panel.innerHTML = '<section role="dialog" aria-modal="true" aria-labelledby="mc-title" style="width:min(620px,96vw);max-height:92vh;overflow:auto;background:#111a2e;color:#e7edf8;border:1px solid #38d0e8;border-radius:14px;padding:18px"><h2 id="mc-title">ربط كاميرا جديدة بمرصاد</h2><p>اختر نوع الاتصال ثم أدخل مصدر الفيديو. لن نعتبر الاتصال ناجحاً حتى تصل إطارات فعلية.</p><label for="mc-type">نوع الكاميرا</label><select id="mc-type" style="width:100%;padding:9px"><option value="phone">كاميرا جوال عبر الشبكة أو USB tethering</option><option value="usb">كاميرا USB / كاميرا يتعرف عليها Windows</option><option value="cctv">كاميرا مراقبة IP أو DVR / NVR</option></select><label for="mc-name">اسم الكاميرا</label><input id="mc-name" maxlength="32" value="PHONE_CAM" style="width:100%;padding:9px"><label for="mc-source">مصدر الفيديو / رقم الكاميرا</label><input id="mc-source" maxlength="512" placeholder="http://192.168.1.20:8080/video أو 0" style="width:100%;padding:9px" autocomplete="off" spellcheck="false"><div id="mc-help" style="background:#17233b;border-radius:8px;padding:10px;margin-top:10px;line-height:1.8"></div><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px"><button id="mc-add" class="ok" type="button">اختبار الاتصال وإضافة</button><button id="mc-close" type="button">إغلاق</button></div><div id="mc-status" role="status" aria-live="polite" style="margin-top:10px;min-height:24px"></div></section>';
    document.body.appendChild(panel);
    const type=$("mc-type"), source=$("mc-source"), name=$("mc-name"), help=$("mc-help"), status=$("mc-status");
    const profiles={
      phone:{name:"PHONE_CAM",placeholder:"http://192.168.1.20:8080/video",help:"على Android: شغّل تطبيق بث كاميرا مثل IP Webcam واضغط Start Server. أدخل رابط MJPEG الذي يعرضه التطبيق. يجب أن يكون الهاتف والكمبيوتر على الشبكة نفسها. عبر كابل USB فعّل USB tethering ثم استخدم رابط البث الذي يعرضه التطبيق."},
      usb:{name:"USB_CAM",placeholder:"0",help:"أدخل رقم كاميرا Windows مثل 0 أو 1 أو 2. إذا كان الهاتف يدعم USB Webcam mode أو تعريف كاميرا افتراضية، اختر رقم الجهاز الذي يظهر في Windows. دعم UVC المباشر يعتمد على الهاتف؛ USB tethering مع بث IP Webcam بديل أكثر توافقاً."},
      cctv:{name:"CCTV_CAM",placeholder:"rtsp://USER:PASSWORD@192.168.1.50:554/STREAM_PATH",help:"أدخل رابط RTSP/RTSPS أو HTTP/MJPEG من الكاميرا أو DVR/NVR. مسار RTSP يختلف حسب الشركة والطراز؛ استخرجه من إعدادات الجهاز. لا تشارك الرابط إذا كان يحتوي على كلمة مرور."}
    };
    function update(){const x=profiles[type.value];name.value=x.name;source.placeholder=x.placeholder;help.textContent=x.help;status.textContent="";status.style.color="";}
    type.addEventListener("change",update);
    open.addEventListener("click",()=>{panel.style.display="flex";update();type.focus();});
    $("mc-close").addEventListener("click",()=>panel.style.display="none");
    panel.addEventListener("click",e=>{if(e.target===panel)panel.style.display="none";});
    update();
    $("mc-add").addEventListener("click",async()=>{
      const rawName=name.value.trim(), src=source.value.trim();
      const n=rawName.replace(/[^A-Za-z0-9_\-\u0600-\u06FF]/g,"").slice(0,32);
      if(!n||!src){status.textContent="أدخل اسم كاميرا صالحاً ومصدر الفيديو.";return;}
      if(n!==rawName){name.value=n;status.textContent="تم تنسيق اسم الكاميرا إلى: "+n;}
      if(/[\r\n\0]/.test(src)||src.length>512){status.textContent="مصدر الفيديو غير صالح.";return;}
      const btn=$("mc-add");btn.disabled=true;type.disabled=true;
      status.style.color="#f2b23a";status.textContent="جارٍ تسجيل المصدر وبدء محرك الكاميرا…";
      try{
        const res=await fetch("/api/cameras/add",{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",body:JSON.stringify({name:n,source:src,spawn_worker:true})});
        const data=await readJson(res,"تعذر تسجيل الكاميرا");
        if(!data.ok)throw new Error(data.error||"تعذر إضافة الكاميرا");
        if(data.worker_spawned===false)throw new Error("تم تسجيل المصدر لكن محرك الكاميرات لم يبدأ. أعد تشغيل مرصاد ثم حاول مجدداً.");
        let cam=null, lastState="لم تظهر حالة الكاميرا بعد";
        // RTSP devices may need the bounded reconnect backoff (up to 15s); 10s was too short.
        for(let i=0;i<30;i++){
          await new Promise(r=>setTimeout(r,1000));
          const lr=await fetch("/api/cameras",{credentials:"same-origin"});
          const list=await readJson(lr,"تعذر قراءة حالة الكاميرات");
          cam=list.cameras&&list.cameras[n];
          if(cam){
            lastState="الحالة: "+(cam.status||"غير معروفة")+" — الإطارات المستلمة: "+Number(cam.frames||0);
            if(cam.status==="online"&&Number(cam.frames||0)>0)break;
          }
          if((i+1)%5===0)status.textContent="الكاميرا مسجلة. ننتظر وصول الفيديو… "+(i+1)+"/30 ثانية. "+lastState;
        }
        if(cam&&cam.status==="online"&&Number(cam.frames||0)>0){
          status.style.color="#35d39a";
          status.textContent="نجح الاتصال: وصلت إطارات فعلية إلى مرصاد. "+lastState;
        }else{
          status.style.color="#f2b23a";
          status.textContent="تم تسجيل الكاميرا، لكن لم يصل فيديو مؤكد خلال 30 ثانية. "+lastState+" تحقق من الشبكة والرابط وبيانات الدخول، ثم أعد المحاولة.";
        }
        window.dispatchEvent(new CustomEvent("mersad:cameras-updated"));
      }catch(e){status.style.color="#ff5d6c";status.textContent=e.message||"فشل الاتصال.";}
      finally{btn.disabled=false;type.disabled=false;}
    });
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();
