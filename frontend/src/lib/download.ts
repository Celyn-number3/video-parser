export function saveFiles(urls: readonly string[]) {
  for (const url of urls) {
    const link = document.createElement('a');
    link.href = url;
    link.download = '';
    document.body.append(link);
    link.click();
    link.remove();
  }
}
