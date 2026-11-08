param(
    [Parameter(Mandatory = $true)] [string] $DllRoot,
    [Parameter(Mandatory = $true)] [string] $GameAssembly,
    [Parameter(Mandatory = $true)] [string] $Cecil,
    [Parameter(Mandatory = $true)] [string] $OutCsv
)

$ErrorActionPreference = 'Stop'
Add-Type -Path (Resolve-Path -LiteralPath $Cecil).Path

function Get-PEImageBase([string] $Path) {
    $fs = [System.IO.File]::OpenRead((Resolve-Path -LiteralPath $Path).Path)
    try {
        $br = [System.IO.BinaryReader]::new($fs)
        $fs.Position = 0x3C
        $peOffset = $br.ReadInt32()
        $fs.Position = $peOffset
        $sig = $br.ReadUInt32()
        if ($sig -ne 0x00004550) { throw "Invalid PE signature in $Path" }
        $fs.Position = $peOffset + 4 + 20
        $magic = $br.ReadUInt16()
        if ($magic -eq 0x20B) {
            $fs.Position = $peOffset + 4 + 20 + 24
            return [UInt64] $br.ReadUInt64()
        }
        if ($magic -eq 0x10B) {
            $fs.Position = $peOffset + 4 + 20 + 28
            return [UInt64] $br.ReadUInt32()
        }
        throw "Unknown PE optional header magic 0x$($magic.ToString('X')) in $Path"
    } finally {
        $fs.Dispose()
    }
}

function Parse-Hex([object] $Value) {
    if ($null -eq $Value) { return $null }
    $s = [string] $Value
    if ([string]::IsNullOrWhiteSpace($s)) { return $null }
    $s = $s.Trim()
    if ($s.StartsWith('0x', [System.StringComparison]::OrdinalIgnoreCase)) { $s = $s.Substring(2) }
    return [UInt64]::Parse($s, [System.Globalization.NumberStyles]::HexNumber)
}

function Get-TypeFullName($typeDef) {
    if ([string]::IsNullOrEmpty($typeDef.Namespace)) { return $typeDef.Name }
    return "$($typeDef.Namespace).$($typeDef.Name)"
}

function Walk-Types($types) {
    foreach ($t in $types) {
        $t
        foreach ($n in (Walk-Types $t.NestedTypes)) { $n }
    }
}

$imageBase = Get-PEImageBase $GameAssembly
$rows = New-Object System.Collections.Generic.List[object]
$dlls = Get-ChildItem -LiteralPath $DllRoot -Filter '*.dll' -File | Sort-Object Name
foreach ($dll in $dlls) {
    $asm = [Mono.Cecil.AssemblyDefinition]::ReadAssembly($dll.FullName)
    try {
        foreach ($type in (Walk-Types $asm.MainModule.Types)) {
            $typeName = Get-TypeFullName $type
            foreach ($method in $type.Methods) {
                $addrAttr = $null
                foreach ($ca in $method.CustomAttributes) {
                    if ($ca.AttributeType.FullName -eq 'Cpp2ILInjected.AddressAttribute') { $addrAttr = $ca; break }
                }
                if ($null -eq $addrAttr) { continue }
                $rva = $null
                $offset = $null
                $length = $null
                foreach ($field in $addrAttr.Fields) {
                    if ($field.Name -eq 'RVA') { $rva = Parse-Hex $field.Argument.Value }
                    elseif ($field.Name -eq 'Offset') { $offset = Parse-Hex $field.Argument.Value }
                    elseif ($field.Name -eq 'Length') { $length = Parse-Hex $field.Argument.Value }
                }
                if ($null -eq $rva) { continue }
                $address = $imageBase + $rva
                $paramTypes = @()
                foreach ($p in $method.Parameters) { $paramTypes += $p.ParameterType.FullName }
                $signature = "$($method.ReturnType.FullName) $typeName::$($method.Name)($($paramTypes -join ', '))"
                $rows.Add([pscustomobject]@{
                    address = ('0x{0:X}' -f $address)
                    rva = ('0x{0:X}' -f $rva)
                    offset = if ($null -ne $offset) { '0x{0:X}' -f $offset } else { '' }
                    length = if ($null -ne $length) { '0x{0:X}' -f $length } else { '' }
                    assembly = $asm.Name.Name
                    type = $typeName
                    method = $method.Name
                    signature = $signature
                    kind = 'managed_method'
                    confidence = 'dummydll-address-attribute'
                }) | Out-Null
            }
        }
    } finally {
        $asm.Dispose()
    }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutCsv) | Out-Null
$rows | Export-Csv -LiteralPath $OutCsv -NoTypeInformation -Encoding UTF8
[pscustomobject]@{
    dllRoot = (Resolve-Path -LiteralPath $DllRoot).Path
    gameAssembly = (Resolve-Path -LiteralPath $GameAssembly).Path
    imageBase = ('0x{0:X}' -f $imageBase)
    outCsv = $OutCsv
    rows = $rows.Count
    assemblies = @($rows | Group-Object assembly | ForEach-Object { [pscustomobject]@{ assembly = $_.Name; rows = $_.Count } })
} | ConvertTo-Json -Depth 5
