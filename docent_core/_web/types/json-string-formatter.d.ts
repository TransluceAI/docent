declare module 'json-string-formatter' {
  interface JsonStringFormatter {
    format(jsonString: string): string | null;
  }

  const jsonStringFormatter: JsonStringFormatter;
  export default jsonStringFormatter;
}
