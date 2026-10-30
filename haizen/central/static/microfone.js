// Captura o microfone em PCM. Roda num AudioWorklet, fora da página, para não
// engasgar a interface. Manda blocos de amostras (Float32) para a página.
class Microfone extends AudioWorkletProcessor {
  process(entradas) {
    const canal = entradas[0] && entradas[0][0];
    if (canal) this.port.postMessage(canal.slice(0));
    return true;
  }
}
registerProcessor("microfone", Microfone);
