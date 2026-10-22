'use strict';
// Only device-local voices are offered. No text is sent to a hosted TTS service.
globalThis.RoomSpeech = class RoomSpeech {
  constructor(synth, Utterance, onStatus=()=>{}) {
    this.synth=synth; this.Utterance=Utterance; this.onStatus=onStatus;
    this.sequence=0; this.utterance=null; this.active=false; this.paused=false; this.queue=[];
  }
  voices() { return this.synth ? this.synth.getVoices().filter(v=>v.localService) : []; }
  stop() {
    this.sequence++; this.active=false; this.paused=false; this.queue=[];
    if(this.synth) this.synth.cancel();
    this.utterance=null; this.onStatus({state:'stopped'});
  }
  pause() {
    if(!this.active)return;
    this.paused=!this.paused;
    if(this.paused)this.synth.pause();else this.synth.resume();
    this.onStatus({state:this.paused?'paused':'speaking',name:this.name});
  }
  speakSequence(entries) { this.stop(); this.queue=entries.slice(); this.speakNext(); }
  speakNext() {
    const entry=this.queue.shift();
    if(entry){try{this.speak(entry.text,entry.character,true);}catch(e){this.stop();this.onStatus({state:'error',message:e.message});}}
  }
  speak(text, character, keepQueue=false) {
    const queue=keepQueue?this.queue:[];
    this.stop();
    this.queue=queue;
    const voices=this.voices();
    if(!this.synth||!this.Utterance||!voices.length)throw new Error('No local voices are available in this browser. Try Chrome or Edge, and install a Windows speech voice if needed.');
    const voice=character.voice_uri ? voices.find(v=>v.voiceURI===character.voice_uri) : voices.find(v=>v.default)||voices.find(v=>v.lang.startsWith('en'))||voices[0];
    if(!voice)throw new Error('This character’s saved voice is unavailable here. Edit the character and choose a voice available on this device.');
    let remaining=text.replace(/[*_`#]/g,'').replace(/\s+/g,' ').trim();
    if(!remaining)return;
    const chunks=[];
    while(remaining.length>220){let cut=remaining.lastIndexOf(' ',220);if(cut<80)cut=220;chunks.push(remaining.slice(0,cut));remaining=remaining.slice(cut).trim();}
    if(remaining)chunks.push(remaining);
    const sequence=this.sequence;this.active=true;this.name=character.name;
    const next=()=>{
      if(sequence!==this.sequence)return;
      if(!chunks.length){this.active=false;this.utterance=null;this.onStatus({state:'stopped'});this.speakNext();return;}
      const utterance=new this.Utterance(chunks.shift());this.utterance=utterance;
      utterance.voice=voice;utterance.lang=voice.lang;utterance.rate=character.speech_rate||1;
      utterance.onstart=()=>{if(sequence===this.sequence)this.onStatus({state:'speaking',name:this.name});};
      utterance.onend=next;
      utterance.onerror=e=>{if(sequence!==this.sequence)return;this.stop();this.onStatus({state:'error',message:`Voice playback failed (${e.error||'unknown error'}). Press Read aloud to try again.`});};
      this.synth.speak(utterance);
    };
    this.onStatus({state:'loading',name:this.name});next();
  }
};
