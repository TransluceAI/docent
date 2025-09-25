/**
 * Determines the next name for a forked item based on versioning and copy patterns
 *
 * @param name - The original name to fork from
 * @returns The new name with incremented version or copy suffix
 */
export function getNextForkName(name: string): string {
  // Check for version patterns

  // Pattern: v1, v2, v3, etc. (ensuring 'v' is not preceded by a letter)
  const simpleVersionMatch = name.match(/^(.*?)(?<![a-zA-Z])v(\d+)$/);
  if (simpleVersionMatch) {
    const [, base, version] = simpleVersionMatch;
    return `${base}v${parseInt(version, 10) + 1}`;
  }

  // Pattern: v1.0, v1.1, v2.0, etc. (major.minor, ensuring 'v' is not preceded by a letter)
  const majorMinorVersionMatch = name.match(
    /^(.*?)(?<![a-zA-Z])v(\d+)\.(\d+)$/
  );
  if (majorMinorVersionMatch) {
    const [, base, major, minor] = majorMinorVersionMatch;
    return `${base}v${major}.${parseInt(minor, 10) + 1}`;
  }

  // Pattern: v1.0.2, v1.0.3, etc. (major.minor.patch, ensuring 'v' is not preceded by a letter)
  const semverMatch = name.match(/^(.*?)(?<![a-zA-Z])v(\d+)\.(\d+)\.(\d+)$/);
  if (semverMatch) {
    const [, base, major, minor, patch] = semverMatch;
    return `${base}v${major}.${minor}.${parseInt(patch, 10) + 1}`;
  }

  // Check for copy patterns

  // Pattern: ends with "(copy)"
  if (name.endsWith('(copy)')) {
    return name.replace(/\(copy\)$/, '(copy 2)');
  }

  // Pattern: ends with "(copy N)"
  const copyNumberMatch = name.match(/^(.*)\(copy (\d+)\)$/);
  if (copyNumberMatch) {
    const [, base, copyNum] = copyNumberMatch;
    return `${base}(copy ${parseInt(copyNum, 10) + 1})`;
  }

  // Default: add " (copy)" to the name
  return `${name} (copy)`;
}
