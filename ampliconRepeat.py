#!/usr/bin/env python

import os
import sys
import numpy as np
import math
import argparse
import subprocess
from sklearn.mixture import GaussianMixture
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt



tab  = '\t'
endl = '\n'
debug = 1
def parse_user_arguments():

    parser = argparse.ArgumentParser(description='Tandem repeat detection from long-read amplicon sequencing data ')
    ### required arguments ###
    parser.add_argument('--in_fq', required = True, metavar = 'input.fastq', type = str, help = 'input fastq file')
    parser.add_argument('--platform', required = True, metavar = 'sequencing_platform', type = str, help = 'two valid values: `ont`, `pacbio`')
    parser.add_argument('--ref_amp_seq', required = True, metavar = 'ref_amplicon_seq.fasta', type = str, help = 'reference amplicon sequence in FASTA format')
    parser.add_argument('--start_pos', required = True, metavar = 'start_pos', type = int, help = 'start position of the repeat in the reference amplicon sequence (1-based)')
    parser.add_argument('--end_pos', required = True, metavar = 'end_pos', type = int, help ='end position of the repeat in the reference amplicon sequence (1-based)')
    parser.add_argument('--repeat_seq', required = True, metavar = 'repeat_seq', type = str, help ='sequence of the repeat unit (e.g. CAG)')
    parser.add_argument('--out_dir', required = True, metavar = 'path/to/output_dir', type = str, help ='path to the output directory')
    parser.add_argument('--version', action='version', version='%(prog)s 0.1.0')

    ### optional arguments ### ploidy
    parser.add_argument('--method', required = False, metavar = 'method for splitting alleles', type = str, default = 'gmm', help ='three valid values: `fixed`, `gmm`, and `both` (default: `gmm`). If `fixed` or `both` is chosen, --fixed_cutoff_value must be specified. ')
    parser.add_argument('--fixed_cutoff_value', required = False, metavar = 'fixed_repeat_count_cutoff_value', type = int, default = -1, help ='split alleles using this fixed_cutoff_value (required if --method is `fixed`)')
    parser.add_argument('--ploidy', required = False, metavar = 'ploidy of the sample', type = int, default = 2, help ='ploidy of the sample (default: 2)')    
    parser.add_argument('--num_threads', required = False, metavar = 'number_of_threads', type = int, default = 1, help ='number of threads used by minimap2 (default: 1)')
    parser.add_argument('--max_num_repeat_unit', required = False, metavar = 'max_num_repeat_unit', type = int, default = 200, help ='maximum possible number of the repeat unit (default: 200)')
    parser.add_argument('--samtools', required = False, metavar = 'samtools', type = str, default = 'samtools', help ='path to samtools (default: using environment default)')
    parser.add_argument('--minimap2', required = False, metavar = 'minimap2', type = str, default = 'minimap2', help ='path to minimap2 (default: using environment default)')
    parser.add_argument('--use_existing_intermediate_files', dest='use_existing_intermediate_files', action='store_true', help='use existing intermediate when rerun the tool (default: False)')
    parser.add_argument('--high_conf_only', dest='high_conf_only', action='store_true', help='only output high confidently phased reads (default: False)')
    parser.set_defaults(use_existing_intermediate_files = False)
    parser.set_defaults(high_conf_only = False)

    input_args = parser.parse_args()

    input_args.method   = input_args.method.strip('`')
    input_args.platform = input_args.platform.strip('`')
    input_args.method   = input_args.method.strip('\'')
    input_args.platform = input_args.platform.strip('\'')
    input_args.method   = input_args.method.strip('\"')
    input_args.platform = input_args.platform.strip('\"')

    valid_platform_list = ['ont', 'pacbio']
    valid_method_list = ['gmm', 'fixed', 'both']
    input_args.platform = input_args.platform.lower()


    if input_args.platform not in valid_platform_list:
        sys.stderr.write('ERROR! --platform should be ont or pacbio !\n')
        sys.exit()

    if (input_args.method == 'fixed' or input_args.method == 'both')and input_args.fixed_cutoff_value == -1:
        sys.stderr.write('ERROR! --fixed_cutoff_value must be specified if --method is `fixed` or `both`!\n')
        sys.exit()
    elif (input_args.method == 'fixed' or input_args.method == 'both') and input_args.fixed_cutoff_value < 1:
        sys.stderr.write('--fixed_cutoff_value must be > 0 !\n')
        sys.exit()

    if (input_args.method == 'gmm' or input_args.method == 'both') and input_args.ploidy < 1:
        sys.stderr.write('--ploidy must be >= 1 !\n')
        sys.exit()

    if input_args.method not in valid_method_list:
        sys.stderr.write('--method must be `fixed`, `gmm`, or `both` !\n')
        sys.exit()

    return input_args

def main():

    input_args = parse_user_arguments()

    ampliconRepeat (input_args)

    return

def ampliconRepeat (input_args):

    samtools            = input_args.samtools
    minimap2            = input_args.minimap2
    ref_amp_seq_file    = input_args.ref_amp_seq
    repeat_seq          = input_args.repeat_seq
    start_pos           = input_args.start_pos
    end_pos             = input_args.end_pos
    in_fastq_file       = input_args.in_fq
    platform            = input_args.platform
    max_num_repeat_unit = input_args.max_num_repeat_unit
    num_threads         = input_args.num_threads
    out_dir             = input_args.out_dir
    method              = input_args.method
    fixed_cutoff_value  = input_args.fixed_cutoff_value
    ploidy              = input_args.ploidy
    high_conf_only      = input_args.high_conf_only


    os.system('mkdir -p %s' % out_dir)
    ref_amp_seq_file = os.path.abspath(ref_amp_seq_file)
    in_fastq_file = os.path.abspath(in_fastq_file)

    template_fasta_file = os.path.join(out_dir, 'temp_template.fasta')

    build_fasta_template (ref_amp_seq_file, repeat_seq, start_pos, end_pos, max_num_repeat_unit, template_fasta_file)
    
    in_fastq_prefix = os.path.splitext(os.path.split(in_fastq_file)[1])[0]
    aligned_bam_file = os.path.join(out_dir, '%s.%s.minimap2.bam' % (in_fastq_prefix, platform))
    
    if input_args.use_existing_intermediate_files == False or os.path.exists(aligned_bam_file) == False:
        align_fastq (samtools, minimap2, platform, num_threads, template_fasta_file, in_fastq_file, aligned_bam_file)
    
    read_repeat_count_dict = calculate_repeat_count_for_each_read (samtools, aligned_bam_file, out_dir)

    if method == 'fixed' or method == 'both':
        split_allele_using_fixed_cutoff_value (samtools, fixed_cutoff_value, read_repeat_count_dict, in_fastq_file, high_conf_only, out_dir)
        
    if method == 'gmm' or method == 'both':
        split_allele_using_gmm(samtools, ploidy, read_repeat_count_dict, in_fastq_file, high_conf_only, out_dir)
        
    ## remove temp files
    if os.path.exists(template_fasta_file) : os.remove(template_fasta_file)
    return


def chose_best_num_components (read_repeat_count_array, ploidy, proba_cutoff, cov_type):

    num_useful_data_points_list = list()
    num_useful_data_points_list.append(0)
    
    max_num_components = ploidy

    bic_list = list()
    bic_list.append(0)

 
    for n in range(1, max_num_components+1):
        gmm = GaussianMixture(n_components=n, covariance_type=cov_type, n_init=10).fit(read_repeat_count_array)
        bic = gmm.bic(read_repeat_count_array)
        bic_list.append(bic)

    min_bic = 1e99
    min_bic_n_components = 0
    for i in range(1, len(bic_list)):
        if bic_list[i] < min_bic:
            min_bic = bic_list[i]
            min_bic_n_components = i

    return min_bic_n_components

def analysis_outlier(read_repeat_count_dict):

    read_repeat_count_list = list()
    for readname in read_repeat_count_dict:
        repeat_count = read_repeat_count_dict[readname]
        read_repeat_count_list.append(repeat_count)

    mean = np.mean(read_repeat_count_list)
    std = np.std(read_repeat_count_list)

    min_repeat_count_cutoff = mean - 3 * std
    if min_repeat_count_cutoff < 0: min_repeat_count_cutoff = 0
    max_repeat_count_cutoff = mean + 3 * std
 
    return min_repeat_count_cutoff, max_repeat_count_cutoff

def split_allele_using_gmm (samtools, ploidy, read_repeat_count_dict, in_fastq_file, high_conf_only, out_dir):

    if ploidy < 1:
        sys.stderr.write('ploidy must be >= 1 !\n')
        sys.exit()

    if high_conf_only:
        proba_cutoff = 0.95
    else:
        proba_cutoff = 0
    cov_type = 'tied'

    min_repeat_count_cutoff, max_repeat_count_cutoff = analysis_outlier(read_repeat_count_dict)
    readname_list = list()
    read_repeat_count_list = list()
    for readname in read_repeat_count_dict:
        repeat_count = read_repeat_count_dict[readname]
        if repeat_count < min_repeat_count_cutoff or repeat_count > max_repeat_count_cutoff: continue 
        readname_list.append(readname)
        read_repeat_count_list.append(repeat_count)

    read_repeat_count_array = np.array(read_repeat_count_list)
    num_data_points = len(read_repeat_count_list)
    read_repeat_count_array = read_repeat_count_array.reshape(num_data_points, 1)

    best_n_components = chose_best_num_components (read_repeat_count_array, ploidy, proba_cutoff, cov_type)
    #best_n_components = ploidy
    final_gmm = GaussianMixture(n_components=best_n_components, covariance_type=cov_type, n_init = 10).fit(read_repeat_count_array)
    old_read_label_list = list(final_gmm.predict(read_repeat_count_array))
    proba2darray = final_gmm.predict_proba(read_repeat_count_array)
    old_cluster_mean_list = list(final_gmm.means_)    

    read_label_list, old_label_to_new_label_dict, new_label_to_old_label_dict = sort_label_by_cluster_mean(old_read_label_list, old_cluster_mean_list)

    read_label_dict = dict()
    read_proba_dict = dict()
    qc_failed_readname_set = set()
    all_info_dict = dict()
    
    each_allele_repeat_count_2d_list = [0] * best_n_components
    for i in range(0, len(each_allele_repeat_count_2d_list)):
        each_allele_repeat_count_2d_list[i] = list()

    for i in range(0, len(readname_list)):
        readname = readname_list[i]
        repeat_count = read_repeat_count_list[i]
        read_label = read_label_list[i]
        read_label_dict[readname] = read_label
        proba_array = proba2darray[i]
        max_prob = max(proba_array)
        read_proba_dict[readname] = max_prob
        info = (repeat_count, read_label, max_prob)
        all_info_dict[readname] = info
        each_allele_repeat_count_2d_list[read_label].append(repeat_count)
        
    if high_conf_only:
        for read_label in range(0, len(each_allele_repeat_count_2d_list)):
            allele_repeat_count_list = each_allele_repeat_count_2d_list[read_label]
            old_label = new_label_to_old_label_dict[read_label]
            gmm_average_repeat_number = old_cluster_mean_list[old_label]
            std = np.std(allele_repeat_count_list)
            max_repeat_number = gmm_average_repeat_number + 3 * std
            min_repeat_number = gmm_average_repeat_number - 3 * std

            for readname in all_info_dict:
                repeat_count, label, max_prob = all_info_dict[readname]
                if max_prob < proba_cutoff: qc_failed_readname_set.add(readname)
                if label == read_label:
                    if repeat_count > max_repeat_number or repeat_count < min_repeat_number:
                        qc_failed_readname_set.add(readname)

        qc_passed_each_allele_repeat_count_2d_list = [0] * best_n_components
        for i in range(0, len(qc_passed_each_allele_repeat_count_2d_list)):
            qc_passed_each_allele_repeat_count_2d_list[i] = list()
        for readname in all_info_dict:
            repeat_count, label, max_prob = all_info_dict[readname]
            if readname not in qc_failed_readname_set:
                qc_passed_each_allele_repeat_count_2d_list[label].append(repeat_count)
    else:
        qc_passed_each_allele_repeat_count_2d_list = each_allele_repeat_count_2d_list


    in_fastq_prefix = os.path.splitext(os.path.split(in_fastq_file)[1])[0]
    if high_conf_only:
        out_prefix = os.path.join(out_dir, '%s.GMM.%s.hich_conf' % (in_fastq_prefix, cov_type))
    else:
        out_prefix = os.path.join(out_dir, '%s.GMM.%s' % (in_fastq_prefix, cov_type))

    out_summray_file = out_prefix + '.summary.txt'
    hist_figure_file = out_prefix + '.hist.png'

    out_allele_fastq_file_list = list()
    for label in range(0, best_n_components):
        allele_id = label + 1
        out_allele_fastq_file = out_prefix + 'allele%d.fastq' % (allele_id)
        out_allele_fastq_file_list.append(out_allele_fastq_file)

    out_allele_fastq_fp_list = list()
    for i in range(0, len(out_allele_fastq_file_list)):
        out_allele_fastq_fp = open(out_allele_fastq_file_list[i], 'w')
        out_allele_fastq_fp_list.append(out_allele_fastq_fp)
    

    if '.gz' == in_fastq_file[-3:]:
        in_fastq_fp = gzip.open(in_fastq_file, 'rt')
    else:
        in_fastq_fp = open(in_fastq_file, 'rt')

    while 1:
        line1 = in_fastq_fp.readline()
        line2 = in_fastq_fp.readline()
        line3 = in_fastq_fp.readline()
        line4 = in_fastq_fp.readline()

        if not line1: break
        if not line2: break
        if not line3: break
        if not line4: break

        readname = line1.strip().split()[0][1:]
        if readname not in read_label_dict: continue
        if readname  in qc_failed_readname_set: continue
    
        label = read_label_dict[readname]
        out_allele_fastq_fp_list[label].write(line1 + line2 + line3 + line4)

    in_fastq_fp.close()

    for i in range(0, len(out_allele_fastq_fp_list)):
        out_allele_fastq_fp_list[i].close()

   
    out_summray_fp = open(out_summray_file, 'w')
    summary_header = '\ninput_fastq=%s' % in_fastq_file
    out_summray_fp.write('##' + summary_header + '\n' )
    sys.stdout.write(summary_header + ';')

    summary_header = 'method=GMM'
    out_summray_fp.write('##' + summary_header + '\n' )
    sys.stdout.write(summary_header + ';')

    predicted_repeat_count_list = list()

    for read_label in range(0, len(qc_passed_each_allele_repeat_count_2d_list)):
        allele_repeat_count_list = qc_passed_each_allele_repeat_count_2d_list[read_label]
        if len(allele_repeat_count_list) == 0: continue
        allele_id = read_label + 1
        num_reads = len(allele_repeat_count_list)
        old_label = new_label_to_old_label_dict[read_label]
        gmm_average_repeat_number = int(old_cluster_mean_list[old_label] + 0.5)
        predicted_repeat_count_list.append(gmm_average_repeat_number)
        average_repeat_number = int(np.mean(allele_repeat_count_list) + 0.5)
        min_repeat_number = min(allele_repeat_count_list)
        max_repeat_number = max(allele_repeat_count_list)
        summary_header = 'allele=%d;num_reads=%d;gmm_average_repeat_number=%.2f;min_repeat_number=%d;average_repeat_number=%.2f;max_repeat_number=%d' % (allele_id, num_reads, gmm_average_repeat_number, min_repeat_number, average_repeat_number, max_repeat_number)
        out_summray_fp.write('##' + summary_header + '\n' )
        sys.stdout.write(summary_header + ';')
    
    sys.stdout.write('\n')

    
    out_info_list = list()
    for readname in all_info_dict:
        if readname in qc_failed_readname_set: continue
        repeat_count, label, max_prob = all_info_dict[readname]
        allele_id = read_label + 1
        out_info = (readname, repeat_count, allele_id, max_prob)
        out_info_list.append(out_info)

    out_info_list.sort(key = lambda x:x[1])

    out_summray_fp.write('#readname\trepeat_count\tallele\n')
    for i in range(0, len(out_info_list)):
        readname, repeat_count, allele_id, max_prob = out_info_list[i]
        if max_prob < proba_cutoff: continue
        out_summray_fp.write('%s\t%d\t%d\t%f\n' % (readname, repeat_count, allele_id, max_prob))

    out_summray_fp.close()

    sum_num_reads = 0
    for allele_repeat_count_list in qc_passed_each_allele_repeat_count_2d_list:
        sum_num_reads += len(allele_repeat_count_list)
    
    if sum_num_reads > 0:
        plot_repeat_counts(qc_passed_each_allele_repeat_count_2d_list, predicted_repeat_count_list, hist_figure_file)

    return 

def plot_repeat_counts(each_allele_repeat_count_2d_list, predicted_repeat_count_list, out_file):

    plt.figure(figsize=(6, 4))

    xmin = 0
    xmax = 100000000

    for i in range(1, len(each_allele_repeat_count_2d_list)):
        if len(each_allele_repeat_count_2d_list[i]) == 0: continue
        if xmin >  min(each_allele_repeat_count_2d_list[i]):
            xmin = min(each_allele_repeat_count_2d_list[i])
        if xmax <  max(each_allele_repeat_count_2d_list[i]):
            xmax = max(each_allele_repeat_count_2d_list[i])

    if xmax - xmin < 200:
        b = range(xmin - 1, xmax + 2)
    else:
        b = range(xmin - 1, xmax + 2, int((xmax - xmin)/200))

    if debug:
        b = range(0, 150)

    for i in range(0, len(each_allele_repeat_count_2d_list)):
        x = each_allele_repeat_count_2d_list[i]
        plt.hist(x, bins = b)

    for repeat_count in predicted_repeat_count_list:
        plt.axvline(x=repeat_count, color = 'grey', linestyle = ':')

    plt.title('Repeat number distribution')
    plt.xlabel('repeat number')
    plt.ylabel('number of reads')
    plt.show()
    plt.savefig(out_file, dpi=300)
    plt.close('all')
    

    return

def sort_label_by_cluster_mean(old_read_label_list, cluster_mean_list):

    l = list()
    for i in range(0, len(cluster_mean_list)):
        label = i
        cluster_mean = cluster_mean_list[i]
        l.append((label, cluster_mean))

    l = sorted(l, key=lambda x:x[1])

    old_label_to_new_label_dict = dict()
    new_label_to_old_label_dict = dict()

    for i in range(0, len(l)):
        new_label = i
        old_label = l[i][0]
        old_label_to_new_label_dict[old_label] = new_label
        new_label_to_old_label_dict[new_label] = old_label

    new_read_label_list = list()

    for i in range(0, len(old_read_label_list)):
        old_label = old_read_label_list[i]
        new_label = old_label_to_new_label_dict[old_label]
        new_read_label_list.append(new_label)

    return new_read_label_list, old_label_to_new_label_dict, new_label_to_old_label_dict

def split_allele_using_fixed_cutoff_value (samtools, fixed_cutoff_value, read_repeat_count_dict, in_fastq_file, high_conf_only, out_dir):

    in_fastq_prefix = os.path.splitext(os.path.split(in_fastq_file)[1])[0]
    out_prefix = '%s.fixed_cutoff_%d' % (in_fastq_prefix, fixed_cutoff_value)

    out_allele1_fastq_file = os.path.join(out_dir, '%s.allele1.fastq' % (out_prefix))
    out_allele2_fastq_file = os.path.join(out_dir, '%s.allele2.fastq' % (out_prefix))
    out_summray_file       = os.path.join(out_dir, '%s.summary.txt' % (out_prefix))
    hist_figure_file       = os.path.join(out_dir, '%s.hist.png' % (out_prefix))

    out_allele1_fastq_fp = open(out_allele1_fastq_file, 'w')
    out_allele2_fastq_fp = open(out_allele2_fastq_file, 'w')
    

    allele1_repeat_count_list = list()
    allele2_repeat_count_list = list()

    if '.gz' == in_fastq_file[-3:]:
        in_fastq_fp = gzip.open(in_fastq_file, 'rt')
    else:
        in_fastq_fp = open(in_fastq_file, 'rt')

    while 1:
        line1 = in_fastq_fp.readline()
        line2 = in_fastq_fp.readline()
        line3 = in_fastq_fp.readline()
        line4 = in_fastq_fp.readline()

        if not line1: break
        if not line2: break
        if not line3: break
        if not line4: break

        readname = line1.strip().split()[0][1:]
        if readname not in read_repeat_count_dict: continue

        repeat_count = read_repeat_count_dict[readname]
        if repeat_count < fixed_cutoff_value:
            allele = 1
            allele1_repeat_count_list.append(repeat_count)
            out_allele1_fastq_fp.write(line1 + line2 + line3 + line4)
        else:
            allele = 2
            allele2_repeat_count_list.append(repeat_count)
            out_allele2_fastq_fp.write(line1 + line2 + line3 + line4)

    in_fastq_fp.close()
    out_allele1_fastq_fp.close()
    out_allele2_fastq_fp.close()

    predicted_repeat_count_list = list()

    out_summray_fp = open(out_summray_file, 'w')
    summary_header = '\ninput_fastq=%s' % in_fastq_file
    out_summray_fp.write('##' + summary_header + '\n' )
    sys.stdout.write(summary_header + ';')
    summary_header = 'method=fixed_cutoff;fixed_cutoff_value=%d' % (fixed_cutoff_value)
    out_summray_fp.write('##' + summary_header + '\n' )
    sys.stdout.write(summary_header + ';')

    num_reads = len(allele1_repeat_count_list)
    if num_reads > 0:
        average_repeat_number = int(np.mean(allele1_repeat_count_list) + 0.5)
        predicted_repeat_count_list.append(average_repeat_number)
        min_repeat_number = min(allele1_repeat_count_list)
        max_repeat_number = max(allele1_repeat_count_list)
        summary_header = 'allele=1;num_reads=%d;average_repeat_number=%d;min_repeat_number=%d;max_repeat_number=%d' % (num_reads, average_repeat_number, min_repeat_number, max_repeat_number)
        out_summray_fp.write('##' + summary_header + '\n' )
        sys.stdout.write(summary_header + ';')
    else:
        summary_header = 'allele=1;num_reads=0;average_repeat_number=-1;min_repeat_number=-1;max_repeat_number=-1'
        out_summray_fp.write('##' + summary_header + '\n' )
        sys.stdout.write(summary_header + ';')
    
    num_reads = len(allele2_repeat_count_list)
    if num_reads > 0: 
        average_repeat_number = int(np.mean(allele2_repeat_count_list) + 0.5)
        predicted_repeat_count_list.append(average_repeat_number)
        min_repeat_number = min(allele2_repeat_count_list)
        max_repeat_number = max(allele2_repeat_count_list)
        summary_header = 'allele=2;num_reads=%d;average_repeat_number=%d;min_repeat_number=%d;max_repeat_number=%d' % (num_reads, average_repeat_number, min_repeat_number, max_repeat_number)
        out_summray_fp.write('##' + summary_header + '\n' )
        sys.stdout.write(summary_header + ';\n')
    else:
        summary_header = 'allele=2;num_reads=0;average_repeat_number=-1;min_repeat_number=-1;max_repeat_number=-1'
        out_summray_fp.write('##' + summary_header + '\n' )
        sys.stdout.write(summary_header + ';\n')
    

    out_info_list = list()
    for readname in read_repeat_count_dict:
        repeat_count = read_repeat_count_dict[readname]
        if repeat_count < fixed_cutoff_value:
            allele_id = 1
        else:
            allele_id = 2
        out_info = (readname, repeat_count, allele_id)
        out_info_list.append(out_info)

    out_info_list.sort(key = lambda x:x[1])

    out_summray_fp.write('#readname\trepeat_count\tallele\n')
    for i in range(0, len(out_info_list)):
        readname, repeat_count, allele_id = out_info_list[i]
        out_summray_fp.write('%s\t%d\t%d\n' % (readname, repeat_count, allele_id))

    out_summray_fp.close()
   
    each_allele_repeat_count_2d_list = [allele1_repeat_count_list, allele2_repeat_count_list]
    
    sum_num_reads = 0
    for allele_repeat_count_list in each_allele_repeat_count_2d_list:
        sum_num_reads += len(allele_repeat_count_list)
    
    if sum_num_reads > 0:
        plot_repeat_counts(each_allele_repeat_count_2d_list, predicted_repeat_count_list, hist_figure_file)

    return



def align_fastq (samtools, minimap2, platform, num_threads, template_fasta_file, in_fastq_file, out_bam_file):

    if platform == 'ont':
        platform_para = 'map-ont'
    elif platform == 'pacbio':
        platform_para = 'map-pb'
    else:
        sys.stderr.write('ERROR! Unknown platform: %s\n' % platform)
        sys.exit()

    cmd = '%s -N 5 --cs -t %d -a -x %s %s %s | %s view -hb - > %s' % (minimap2, num_threads, platform_para, template_fasta_file, in_fastq_file, samtools, out_bam_file)

    os.system(cmd)
    sys.stderr.write('NOTICE: Running command: `%s`\n' % (cmd))
   
    return


def build_fasta_template(ref_amp_seq_file, repeat_seq, start_pos, end_pos, max_num_repeat_unit, template_fasta_file):

    fasta_name_list, fasta_seq_list = read_fasta_file(ref_amp_seq_file)

    if len(fasta_name_list) < 1:
        sys.stderr.write('ERROR! FILE: %s has no valid sequence!\n' % ref_amp_seq_file)
        sys.exit()

    if len(fasta_name_list) > 1:
        sys.stderr.write('ERROR! There are multiple sequences in FILE: %s! There should be only one amplicon sequence' % ref_amp_seq_file)
        sys.exit()

    ref_amp_name = fasta_name_list[0]
    ref_amp_seq  = fasta_seq_list[0]

    start_pos -= 1

    left_fasta_seq  = ref_amp_seq[0:start_pos]
    right_fasta_seq = ref_amp_seq[end_pos:]

 
    max_flanking_len = 50000

    if len(left_fasta_seq)  > max_flanking_len:  left_fasta_seq = left_fasta_seq[-max_flanking_len:]
    if len(right_fasta_seq) > max_flanking_len:  right_fasta_seq = right_fasta_seq[0:max_flanking_len]

    template_fasta_fp = open(template_fasta_file, 'w')
    max_base_per_line = 100

    for repeat_count in range(1, max_num_repeat_unit + 1):
        template_fasta_fp.write('>%d\n' % repeat_count)
        seq = left_fasta_seq + repeat_seq * repeat_count + right_fasta_seq
        for i in range(0, len(seq), max_base_per_line):
            start_pos = i
            end_pos = i + max_base_per_line
            if end_pos > len(seq): end_pos = len(seq)
            template_fasta_fp.write('%s\n' % seq[start_pos:end_pos])

    template_fasta_fp.close()

    return

def read_fasta_file(fasta_file):

    if '.gz' == fasta_file[-3:]:
        fasta_fp = gzip.open(fasta_file, 'rt')
    else:
        fasta_fp = open(fasta_file, 'rt')

    fasta_name_list = list()
    fasta_seq_list = list()
    curr_name = ''
    curr_seq = ''

    while 1:
        line = fasta_fp.readline()
        if not line: break
        line = line.strip()
        if not line: continue
        if line[0] ==  '>':
            if len(curr_seq) > 0 and len(curr_name) > 0:
                fasta_name_list.append(curr_name)
                fasta_seq_list.append(curr_seq)
            curr_name = line[1:]
            curr_seq = ''
            continue

        curr_seq += line
     
    fasta_fp.close()

    if len(curr_seq) > 0 and len(curr_name) > 0:
        fasta_name_list.append(curr_name)
        fasta_seq_list.append(curr_seq)
    
    return fasta_name_list, fasta_seq_list


def calculate_repeat_count_for_each_read (samtools, in_bam_file, out_dir):

    bam_file_name = os.path.split(in_bam_file)[1]
    bam_prefix    = os.path.splitext(bam_file_name)[0]

    out_coreinfo_file = os.path.join(out_dir, '%s.coreinfo.txt' % bam_prefix)
    cmd = '%s view -F 4 -F 256 -F 2048 %s | cut -f 1-5 > %s' % (samtools, in_bam_file, out_coreinfo_file)
    sys.stderr.write ('NOTICE: running command: `%s` \n' % cmd)
    os.system(cmd)

    read_repeat_count_dict = dict()
    out_coreinfo_fp = open(out_coreinfo_file, 'r')

    while 1:
        line = out_coreinfo_fp.readline()
        if not line: break
        line = line.strip().split(tab)
        if len(line) != 5:
            sys.stderr.write ('ERROR! invalid alignment: %s \n' % ('\t'.join(line)))
            sys.exit()
        readname = line[0]
        flag = int(line[1])
        contig = line[2]
        if flag & 256 or flag & 2048: continue

        repeat_count = int(contig)
        read_repeat_count_dict[readname] = repeat_count

    out_coreinfo_fp.close()

    os.remove(out_coreinfo_file)

    return read_repeat_count_dict



if __name__ == '__main__':
    main()
