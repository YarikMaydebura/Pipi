// Browser-side runtime every WebSocket body shares (desktop pet, fake robot): the brain link
// (hello, validation, acks, reconnect with backoff) and speech (WAV playback with Web Audio,
// captions, loudness for the talking animation, speech_done timing). Sharing it keeps the
// bodies indistinguishable to the brain.
export * from './audioPlayer';
export * from './backoff';
export * from './base64';
export * from './brainClient';
export * from './speechBubble';
export * from './speechController';
export * from './timing';
