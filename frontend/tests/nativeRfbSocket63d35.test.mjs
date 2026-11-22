import test from "node:test";
import assert from "node:assert/strict";
import {
  createNativeRfbSocket, MAX_RFB_BUFFERED_BYTES,
} from "../src/pages/clientdetailspage/remotedesktop/nativeRfbSocket.mjs";
import { encodeNativeRdpChunk } from "../src/pages/clientdetailspage/remotedesktop/nativeRdpBridgeProtocol.mjs";

const sessionId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const streamId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const wrongStream = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const state = (type) => ({type, protocol:1, session_id:sessionId, stream_id:streamId});
function fakeTransport() {
  return {
    sent:[], closes:[], onmessage:null, onerror:null, onclose:null,
    send(raw) { this.sent.push(JSON.parse(raw)); },
    close(code, reason) { this.closes.push([code,reason]); },
    incoming(data) { this.onmessage?.({data:JSON.stringify(data)}); },
  };
}
function connected() {
  const transport = fakeTransport();
  const socket = createNativeRfbSocket({transport,sessionId});
  transport.incoming(state("native_rdp_pending"));
  transport.incoming(state("native_rdp_ready"));
  assert.equal(socket.readyState,1);
  return {transport,socket};
}

test("noVNC-compatible raw channel shape is complete, never sends RDP before ready", () => {
  const transport=fakeTransport();
  const socket=createNativeRfbSocket({transport,sessionId});
  for (const key of ["send","close","binaryType","onerror","onmessage",
                    "onopen","protocol","readyState"]) {
    assert.ok(key in socket,key);
  }
  assert.equal(socket.readyState,0);
  assert.throws(()=>socket.send(new Uint8Array([1])));
  let opened=0;socket.onopen=()=>opened++;
  transport.incoming(state("native_rdp_pending"));
  assert.equal(opened,0);
  transport.incoming(state("native_rdp_ready"));
  assert.equal(opened,1);
});

test("noVNC binary output is copied, ordered, bounded and ACK-fed", () => {
  const {transport,socket}=connected();
  const bytes=new Uint8Array(18*1024);
  bytes.fill(9);
  socket.send(bytes);
  bytes.fill(1);
  assert.deepEqual(transport.sent.map(m=>m.seq),[0,1]);
  assert.equal(transport.sent[0].data.slice(0,8),"CQkJCQkJ");
  transport.incoming({...state("native_rdp_ack"),seq:0});
  transport.incoming({...state("native_rdp_ack"),seq:1});
  assert.equal(socket.readyState,1);
});

test("RFB inbound packets are delivered as ArrayBuffer and ACKed after callback", () => {
  const {transport,socket}=connected();
  const delivered=[];socket.onmessage=e=>delivered.push(new Uint8Array(e.data));
  transport.incoming(encodeNativeRdpChunk({sessionId,streamId,seq:0,
    bytes:new Uint8Array([0,0,255,65])}));
  assert.deepEqual(delivered,[new Uint8Array([0,0,255,65])]);
  assert.equal(transport.sent.at(-1).type,"native_rdp_ack");
  assert.equal(transport.sent.at(-1).seq,0);
});

test("replays, stale generations, invalid ACK and forged messages close fail-closed", () => {
  for(const msg of [
    {...state("native_rdp_chunk"),seq:0,data:"AA==",stream_id:wrongStream},
    {...state("native_rdp_ack"),seq:0},
    {...state("native_rdp_ready")},
    {...state("native_rdp_chunk"),seq:10,data:"AA=="},
    {type:"frame",session_id:sessionId,data:"JPEG"},
  ]) {
    const {transport,socket}=connected();
    transport.incoming(msg);
    assert.equal(socket.readyState,3);
    assert.equal(transport.closes.length,1);
  }
});

test("bounded synchronous outgoing noVNC send cannot silently lose input", () => {
  const {socket,transport}=connected();
  const bytes=new Uint8Array(MAX_RFB_BUFFERED_BYTES);
  socket.send(bytes);
  assert.equal(transport.sent.length,8);
  assert.throws(()=>socket.send(new Uint8Array([1])));
  assert.equal(socket.readyState,3);
  assert.equal(transport.closes.length,1);
});

test("server close and browser close erase queue and release session", () => {
  const {socket,transport}=connected();
  socket.close();
  assert.equal(socket.readyState,3);
  assert.equal(transport.sent.at(-1).type,"native_rdp_close");
  assert.equal(transport.closes.length,1);
  transport.incoming(state("native_rdp_ready"));
  assert.equal(transport.closes.length,1);

  const next=connected();
  next.transport.incoming(state("native_rdp_close"));
  assert.equal(next.socket.readyState,3);
});

test("one RFB session cannot be retargeted to a different browser session", () => {
  assert.throws(()=>createNativeRfbSocket({transport:fakeTransport(),sessionId:"wrong"}));
  const transport=fakeTransport();
  const socket=createNativeRfbSocket({transport,sessionId});
  transport.incoming({...state("native_rdp_pending"),session_id:wrongStream});
  assert.equal(socket.readyState,3);
});
