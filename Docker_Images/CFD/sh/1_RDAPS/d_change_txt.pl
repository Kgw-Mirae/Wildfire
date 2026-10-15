#!/usr/bin/perl
use strict;
use warnings;
use File::Path qw(make_path);

# ==========================================================
# RDAPS extraction TXT post-processing
# Reads rdaps_dates.txt and RDAPS_point.txt to process real grid indices
# ==========================================================

# -----------------------------
# Directory paths
# -----------------------------
my $source_env = "./rdaps_source_plan.env";
my $source_type = "nc_pres";
if (-f $source_env) {
    open my $sfh, "<:encoding(UTF-8)", $source_env
      or die "Cannot open $source_env: $!";
    while (my $line = <$sfh>) {
        chomp $line;
        if ($line =~ /^RDAPS_SOURCE_TYPE="([^"]+)"/) {
            $source_type = $1;
            last;
        }
    }
    close $sfh;
}

my $indir    = ($source_type eq "nc_pres") ? "./1_nc" : "./1_gb2";
my $outdir   = "./txt";              # Output TXT directory
my $datefile = "./rdaps_dates.txt";              # RDAPS date list (YYYY.MM.DD.HH)
my $pointfile = "./RDAPS_point.txt"; # RDAPS point list (x y lon lat)

# Create output directory if not existing
make_path($outdir) unless -d $outdir;

# -----------------------------
# Variable list
# -----------------------------
my @vars = qw(u v tmp hgt);  # or qw(tmp u v spfh)

# -----------------------------
# Read date list
# -----------------------------
open my $dfh, "<:encoding(UTF-8)", $datefile
  or die "Cannot open $datefile: $!";
my @dates;
while (my $line = <$dfh>) {
    chomp $line;
    next if $line =~ /^\s*$/;   # skip blank
    next if $line =~ /^\s*#/;   # skip comment
    $line =~ s/\s+//g;          # remove spaces
    push @dates, $line;
}
close $dfh;

# -----------------------------
# Read LDAPS point indices
# -----------------------------
open my $pfh, "<:encoding(UTF-8)", $pointfile
  or die "Cannot open $pointfile: $!";
my @points;
while (my $line = <$pfh>) {
    chomp $line;
    next if $line =~ /^\s*$/;
    next if $line =~ /^\s*#/;
    my ($x, $y, $lon, $lat) = split /\s+/, $line;
    push @points, [$x, $y];
}
close $pfh;

# -----------------------------
# Main conversion loop
# -----------------------------
foreach my $dt (@dates) {
    my ($yy, $mm, $dd, $HH) = split /\./, $dt;
#    printf "Processing date %s-%s-%s %sH...\n", $yy, $mm, $dd, $HH;
#    printf "===== Step 4: Interpolation LDAPS =====";

    foreach my $fcast (qw(000)) {
        foreach my $var (@vars) {

            my $HHHH = $HH + $fcast;
            my $H = sprintf("%02d", $HHHH % 24);  # wrap at 24h

            foreach my $p (@points) {
                my ($x, $y) = @$p;

                my $infile  =
"$indir/${x}_${y}_${yy}${mm}${dd}${H}_${var}.txt";
                my $outfile =
"$outdir/${x}_${y}_${yy}${mm}${dd}${H}_${var}.txt";

                unless (-f $infile) {
                    warn "Missing: $infile\n";
                    next;
                }

                open my $in,  "<:encoding(UTF-8)", $infile
                  or die "Cannot open $infile: $!";
                open my $out, ">:encoding(UTF-8)", $outfile
                  or die "Cannot write $outfile: $!";

                while (my $line = <$in>) {
                    chomp $line;
                    if ($line =~ /^\s*[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?\s*$/) {
                        printf $out "%11.8f\n", $line;
                        next;
                    }

                    my @cols = split /,/, $line;
                    next unless @cols >= 3;
                    my @kv = split /=/, $cols[2];
                    printf $out "%11.8f\n", $kv[1] if defined $kv[1];
                }

                close $in;
                close $out;
            }
        }
    }
}

#print "\n[OK] successfully.\n";
