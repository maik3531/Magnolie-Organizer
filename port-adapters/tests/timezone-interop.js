/* Read-only actual App parity:148 checks, plus37 separately retained raw OS diagnostics.
 * No Intl patch, occurrence expansion, save or native ACK is performed here. */
(() => {
  'use strict';
  window.NativeTimezoneInterop = {
    run(fixture) {
      const T=window.OrganizerTest,book=T.daten(),before=JSON.stringify(book),regional=book.einstellungen.regional;
      const own=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
      const saved={timeZone:{had:own(regional,'timeZone'),value:regional.timeZone},formatLocale:{had:own(regional,'formatLocale'),value:regional.formatLocale}};
      const failures=[],osFailures=[];let checks=0,osChecks=0;
      const compare=(row,path,actual,expected)=>{checks++;if(actual!==expected)failures.push({identifier:row.identifier,wall:row.wall,path,expected,actual});};
      const offsetLabel=seconds=>{if(seconds===0)return 'UTC';const absolute=Math.abs(seconds),pad=v=>String(v).padStart(2,'0');return 'UTC'+(seconds<0?'-':'+')+pad(Math.floor(absolute/3600))+':'+pad(Math.floor(absolute/60)%60)+(absolute%60?':'+pad(absolute%60):'');};
      try {
        regional.formatLocale='en-CA';
        const surface=window.MagnolieI18n?.locale() || '';
        const locale=/^[a-z]{2,3}(?:-|$)/i.test(surface)?surface.split('-')[0]+'-CA':'en-CA';
        for(const row of fixture.clocks) {
          regional.timeZone=row.identifier;const [datum,zeit]=row.wall.split('T');
          try{compare(row,'actual-appointment-reminder',+T.terminZeitpunkt({datum,zeit}),row.epochMs);}catch(error){compare(row,'actual-appointment-reminder',String(error),row.epochMs);}
          const stamp=row.wall.replace(/[-:]/g,'')+'00';
          try {
            const values=T.icsExpansion({icsRoundtrip:['DUE;TZID='+row.identifier+':'+stamp]},-Infinity,Infinity,true);
            compare(row,'actual-task-count',values?.length,1);compare(row,'actual-task-reminder',values?.[0]?.icsStartUtc,row.epochMs);
          }catch(error){compare(row,'actual-task-reminder',String(error),row.epochMs);}
          try {
            const options={timeZone:row.identifier,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23',timeZoneName:'short'};
            const [year,month,day]=datum.split('-').map(Number),[hour,minute]=zeit.split(':').map(Number),carrier=new Date(0);
            carrier.setUTCFullYear(year,month-1,day);carrier.setUTCHours(hour,minute,0,0);
            const expected=new Intl.DateTimeFormat(locale,{...options,timeZone:'UTC'}).formatToParts(carrier)
              .map(part=>part.type==='timeZoneName'?offsetLabel(row.offsetSeconds):part.value).join('');
            compare(row,'actual-datumText-with-offset',T.datumText(new Date(row.epochMs),options,false),expected);
          }catch(error){compare(row,'actual-datumText-with-offset',String(error),row.wall);}
          // This engine is intentionally unmodified and is not a point-rule authority.
          osChecks++;
          try {
            const p=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:row.identifier,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'})
              .formatToParts(new Date(row.epochMs)).filter(part=>part.type!=='literal').map(part=>[part.type,part.value]));
            const actual=p.year+'-'+p.month+'-'+p.day+'T'+p.hour+':'+p.minute;
            if(actual!==row.wall)osFailures.push({identifier:row.identifier,wall:row.wall,expected:row.wall,actual});
          }catch(error){osFailures.push({identifier:row.identifier,wall:row.wall,error:String(error)});}
        }
      }finally{for(const [key,value]of Object.entries(saved)){if(value.had)regional[key]=value.value;else delete regional[key];}}
      if(JSON.stringify(book)!==before)throw new Error('Timezone audit changed the book');
      return {clocks:fixture.clocks.length,checks,failures,appParity:failures.length===0,osIntlParity:osFailures.length===0,
        usedForPointRules:'normative-tzif-posix',providerIdentity:window.MagnolieTime.identity,
        osIntlDiagnostics:{checks:osChecks,failures:osFailures,usedForPointRules:false},bookUnchanged:true};
    }
  };
})();
