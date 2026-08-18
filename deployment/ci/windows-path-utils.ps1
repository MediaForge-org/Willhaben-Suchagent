# Windows path comparison helpers for the release smoke test.
#
# Windows paths are case-insensitive (NTFS preserves case but does not use it
# for identity), but PowerShell string operators (-eq, .StartsWith(),
# .Contains()) are case-sensitive by default. A relocated-release path like
# "C:\Temp\..." vs an expected "C:\temp\..." is the *same* filesystem path
# and must compare equal. Kept in a separate file (rather than inline in
# windows-smoke-test.ps1) so it can be dot-sourced and unit-tested on its own
# without running the full smoke test.

function Get-NormalizedWindowsPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    # Resolves to a full, backslash-consistent path and strips any trailing
    # separator, so "C:\foo\" and "C:\foo" normalize identically before
    # comparison.
    return ([System.IO.Path]::GetFullPath($Path)).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
}

function Test-WindowsPathsEqual {
    param(
        [Parameter(Mandatory = $true)][string]$PathA,
        [Parameter(Mandatory = $true)][string]$PathB
    )
    $normA = Get-NormalizedWindowsPath $PathA
    $normB = Get-NormalizedWindowsPath $PathB
    return [string]::Equals($normA, $normB, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-WindowsPathIsUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )
    $normPath = Get-NormalizedWindowsPath $Path
    $normRoot = Get-NormalizedWindowsPath $Root
    if ([string]::Equals($normPath, $normRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    # Require the separator so "C:\temp\foo" is never mistaken as being
    # under root "C:\temp\foobar" (or vice versa) - a plain StartsWith on
    # the un-separated strings would match that false positive.
    $rootWithSeparator = $normRoot + [System.IO.Path]::DirectorySeparatorChar
    return $normPath.StartsWith($rootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-TextContainsWindowsPath {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $normPath = Get-NormalizedWindowsPath $Path
    return $Text.IndexOf($normPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}
