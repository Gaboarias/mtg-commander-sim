// Descarga de un archivo de texto desde el navegador (Blob + <a download>).
// Centraliza lo que antes estaba duplicado en /, /play y /watch.
export function download(name: string, text: string, type: string) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

// Sello de tiempo apto para nombres de archivo (YYYY-MM-DD-HH-MM-SS).
export function fileStamp(): string {
  return new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
}
