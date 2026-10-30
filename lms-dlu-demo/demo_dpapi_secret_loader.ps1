param([Parameter(Mandatory=$true)][string]$SecretPath)
$ErrorActionPreference = 'Stop'
try {
    $encrypted = Get-Content -LiteralPath $SecretPath -Raw
    if ([string]::IsNullOrWhiteSpace($encrypted)) { exit 2 }
    $secure = ConvertTo-SecureString -String $encrypted
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
} catch { exit 2 }
