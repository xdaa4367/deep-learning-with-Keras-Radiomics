#!/usr/bin/env python3.5
"""Calculate statistics of a 3D dataset."""
import os
import sys
import argparse
import imageio
import numpy as np
from PIL import Image, ImageChops
from single_experiment_runner import load_organized_dataset, plot_slices
from single_experiment_runner import limit_number_patients_per_label
from matplotlib import pyplot as plt
from keras.utils import np_utils
from scipy.ndimage.morphology import binary_erosion
from skimage import feature
from scipy.stats import ks_2samp, iqr, expon
sys.path.insert(0, 'create_datasets')
from save_datasets import calculate_shared_axis, plot_boxplot, plot_histogram
from save_datasets import save_plt_figures_to_pdf, analyze_data, simple_plot_histogram
from parse_volumes_dataset import plot_pet_slice


def get_statistics_mask(mask):
    """Get size box and volume of mask where we can fit all 1s in contour."""
    ones_pos = np.nonzero(mask)
    eroded = binary_erosion(mask)
    outer_mask = mask - eroded
    volume = len(ones_pos[0])
    surface = outer_mask.sum()
    return surface, volume, ones_pos


def get_glcm_statistics(volume):
    """Get statistics realted to GLCM."""
    # very technically, GLCMs are only defined in 2d and there is
    # considerable disagreement as to how to translate them into 3d.
    # the common practice for small, similar objects like yours
    # therefore is to select typical images from the volume. this
    # can be a few slices toward the middle and average or even just
    # use the median slice. Here I am using the median slice
    image_array = volume[:, :, int(volume.shape[2] / 2)]
    # skimage will compute the GLCM for multiple pixel offsets
    # at once; we only need nearest neighbors so the offset is 1
    offsets = np.array([1]).astype(np.int)
    # the values of GLCM statistics from 0, 45, 90, 135 usually
    # are averaged together, especially for textures we expect
    # to be reasonably random
    radians = np.pi * np.arange(4) / 4
    # skimage is kind of stupid about counting so you must make sure
    # that number of levels matches what your data *can* be, not what
    # they are. the problem is that the matrices are too sparse using
    # all levels on small, low contrast images. therefore we downsample
    # the shades to something reasonable. FYI: this is properly done
    # via histogram matching but no MD ever does this correctly. instead
    # they do (again, this is *INCORRECT* (but quite common in the field)):
    LEVELS = 16
    lo, hi = image_array.min(), image_array.max()
    image_array = np.round((image_array - lo) / (hi - lo) * (LEVELS - 1)).astype(np.uint8)
    # Calculate co-matrix
    glcms = feature.greycomatrix(image_array, offsets, radians, LEVELS, symmetric=True,
                                 normed=True)
    # compute the desired GLCM statistic
    dissimil = feature.greycoprops(glcms, prop='dissimilarity')
    # now that you have a GLCM for each offset and each direction, average over direction
    # 0 because there is only one offset
    dissimil = [dissimil[0, angle] for angle in range(radians.size)]
    dissimil = np.mean(dissimil)
    correlation = feature.greycoprops(glcms, prop='correlation')
    correlation = [correlation[0, angle] for angle in range(radians.size)]
    correlation = np.mean(correlation)
    asm = feature.greycoprops(glcms, prop='ASM')
    asm = [asm[0, angle] for angle in range(radians.size)]
    asm = np.mean(asm)
    return dissimil, correlation, asm


def read_dataset(dataset_location, num_patients_per_label=None, slices_plot=False, plot=False):
    """Read and transfrom dataset."""
    train_set, test_set, train_aux, test_aux = load_organized_dataset(dataset_location)
    (x_train, y_train), (x_test, y_test), = train_set, test_set
    (patients_train, mask_train), (patients_test, mask_test) = train_aux, test_aux
    try:
        x_whole = np.append(x_train, x_test, axis=0)
    except ValueError:
        x_whole = x_train + x_test
    try:
        y_whole = np.append(y_train, y_test, axis=0)
    except ValueError:
        y_whole = y_train + y_test
    try:
        mask_whole = np.append(mask_train, mask_test, axis=0)
    except ValueError:
        mask_whole = mask_train + mask_test
    try:
        patients_whole = np.append(patients_train, patients_test, axis=0)
    except ValueError:
        patients_whole = patients_train + patients_test
    analyze_data(x_whole, y_whole, patients_whole, mask_whole, plot_data=plot, dataset_name=None)

    # Remove elements of the dataset if necessary
    if num_patients_per_label is not None:
        params = limit_number_patients_per_label(x_whole, y_whole, mask_whole, patients_whole,
                                                 num_patients_per_label=num_patients_per_label)
        x_whole, y_whole, mask_whole, patients_whole = params
        analyze_data(x_whole, y_whole, patients_whole, mask_whole, plot_data=plot,
                     dataset_name=None)
    plt.close("all")

    patients = np.unique(patients_whole)
    num_patients = len(patients)
    labels = np.unique(y_whole)
    y_whole = np_utils.to_categorical(y_whole, len(labels))

    if slices_plot:
        i = 0
        plt.ion()
        while i < len(x_whole):
            s = "{}/{} - Patient: {} - Label: {}".format(i, len(x_whole), patients_whole[i],
                                                         y_whole[i][1])
            plot_slices(x_whole[i], title=s, fig_num=0)
            print(s)
            r = input("ENTER: next slice, q: quit plot, n: next patient.\n>> ")
            if len(r) > 0 and r[0].lower() == "q":
                break
            elif len(r) > 0 and r[0].lower() == "n":
                p = patients_whole[i]
                while i < len(patients_whole) and patients_whole[i] == p:
                    i += 1
            else:
                i += 1
        plt.close("all")
        plt.ioff()

    # Print some information of data
    try:
        print("Whole set shape:     {}".format(x_whole.shape))
    except AttributeError:
        print("Whole set size:     {}".format(len(x_whole)))
    print("Existing labels:     {}".format(labels))
    print("Number of patients:  {}".format(num_patients))
    try:
        print("Number of slices:    {}".format(x_whole.shape[0]))
    except AttributeError:
        pass

    return x_whole, y_whole, mask_whole, patients_whole


def parse_arguments():
    """Parse arguments in code."""
    parser = argparse.ArgumentParser(description="Calculate several statistics from dataset.")
    parser.add_argument('-p', '--plot', default=False, action="store_true",
                        help="show figures before saving them")
    parser.add_argument('-ps', '--plot_slices', default=False, action="store_true",
                        help="show slices of volume in dataset")
    parser.add_argument('-s', '--size', default=None, type=int,
                        help="max number of patients per label (default: all)")
    parser.add_argument('-d', '--dataset', default="organized", type=str,
                        help="location of the dataset inside the ./data folder "
                        "(default: organized)")
    parser.add_argument('-v', '--verbose', default=False, action="store_true", help="enable "
                        "verbose mode when training")
    parser.add_argument('-dr', '--dry_run', default=False, action="store_true", help="do not "
                        "save pdf with results")
    parser.add_argument('-sd', '--save_dataset', default=False, action="store_true", help="save "
                        "a features dataset (mean, std, volume...)")
    parser.add_argument('-ss', '--save_slices', default=False, action="store_true", help="save "
                        "median slice and median slice with mask images")
    parser.add_argument('-f', '--factor', default=False, action="store_true",
                        help="multiply all data by 255")
    parser.add_argument('-pvi', '--plot_volume_histogram', default=False, action="store_true",
                        help="plot volume histogram and boxplots, and calculate volume metrics")
    return parser.parse_args()


def plot_metric(data0, data1, label0="Metrics 0", label1="Metrics 1", label_all="Metrics Total",
                figure=0, plot_data=True, window_histogram="Histogram",
                window_boxplot="Boxplot", simple_histograms=False, one_histogram=False):
    """Plot histogram and boxplot for label0 and label1."""
    print("Generating figures for: {} ...".format(label_all))
    num_bins = 20
    if plot_data:
        plt.ion()
    xlim = calculate_shared_axis(data0, data1)
    if one_histogram:
        # Formula Frank to know number bins
        num_bins0 = max(int(2 * iqr(data0) / (len(data0) ** (1 / 3))), num_bins)
        num_bins1 = max(int(2 * iqr(data1) / (len(data1) ** (1 / 3))), num_bins)
        if not simple_histograms:
            plot_histogram(data0, label0, figure, 111, num_bins0, xlim, show=plot_data,
                           label_histogram="Label 0", figsize=None, alpha=0.6)
            plot_histogram(data1, label1, figure, 111, num_bins1, xlim, show=plot_data, alpha=0.6,
                           window_title=window_histogram, label_histogram="Label 1", figsize=None)
        else:
            simple_plot_histogram(data0, label0, figure, 111, num_bins0, xlim, show=plot_data,
                                  label_histogram="Label 0", figsize=None, alpha=0.6)
            simple_plot_histogram(data1, label1, figure, 111, num_bins1, xlim, show=plot_data,
                                  window_title=window_histogram, label_histogram="Label 1",
                                  figsize=None, alpha=0.6)
    else:
        if not simple_histograms:
            plot_histogram(data0, label0, figure, 311, num_bins, xlim, show=plot_data)
            plot_histogram(data1, label1, figure, 312, num_bins, xlim, show=plot_data)
            plot_histogram(data0 + data1, label_all, figure, 313, num_bins, xlim,
                           window_title=window_histogram, show=plot_data)
        else:
            simple_plot_histogram(data0, label0, figure, 311, num_bins, xlim, show=plot_data)
            simple_plot_histogram(data1, label1, figure, 312, num_bins, xlim, show=plot_data)
            simple_plot_histogram(data0 + data1, label_all, figure, 313, num_bins, xlim,
                                  window_title=window_histogram, show=plot_data)

    ylim = calculate_shared_axis(data0, data1)
    plot_boxplot(data0, label0, figure + 1, 121, ylim, show=plot_data)
    plot_boxplot(data1, label1, figure + 1, 122, ylim, True, show=plot_data,
                 window_title=window_boxplot)
    if plot_data:
        plt.ioff()


def calculate_similarity(list0, list1, num_samples=10000):
    """Calculate similarity between 2 1d arrays with ks_2samp."""
    similarity = ks_2samp(list0, list1)
    list0_sampled = np.random.choice(list0, num_samples)
    list1_sampled = np.random.choice(list1, num_samples)
    similarity_sampled = ks_2samp(list0_sampled, list1_sampled)
    print("Similarity of all data (Shape: {} - {}):\n  {}".format(np.array(list0).shape,
                                                                  np.array(list1).shape,
                                                                  similarity))
    print("Similarity after sampling data ({} samples):\n  {}".format(num_samples,
                                                                      similarity_sampled))


def remove_background_color(im):
    """Remove background frame in an image."""
    bg = Image.new(im.mode, im.size, im.getpixel((0, 0)))
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    bbox = diff.getbbox()
    if bbox:
        return im.crop(bbox)
    return im


def save_images_median_slice(x_whole, y_whole, mask_whole, patients_whole):
    """Save every median slice as an image with and without mask, and image with all medians."""
    folder = "median_images"
    try:
        os.mkdir(folder)
    except FileExistsError:
        pass
    plt.close("all")
    labels = y_whole[:, 1]
    order = [[], []]
    for i, label in enumerate(labels):
        order[int(label)].append(i)
    order = order[0] + order[1]
    if len(labels) == 77:
        h, w = 7, 11
    elif len(labels) == 60:
        h, w = 6, 10
    else:
        h = int(np.floor(np.sqrt(len(labels))))
        w = int(np.ceil(np.sqrt(len(labels))))
        if w * h < len(labels):
            h += 1
    result = None
    result_mask = None
    img_w = None
    img_h = None
    for i, idx in enumerate(order):
        (x, y, m, p) = x_whole[idx], labels[idx], mask_whole[idx], patients_whole[idx]
        filename = "Patient {} - Label {}".format(p, int(y))
        image_path = "{}/{}.png".format(folder, filename)
        mask_path = "{}/{}_masked.png".format(folder, filename)
        plot_pet_slice(x, mask=None, center=int(x.shape[2] / 2), label=filename, figure=0,
                       square_pixels=True, show_axis=False, quit_immediately=True)
        plt.savefig(image_path, bbox_inches='tight')
        plot_pet_slice(x, mask=m, center=int(x.shape[2] / 2), label=filename, figure=1,
                       square_pixels=True, show_axis=False, quit_immediately=True)
        plt.savefig(mask_path, bbox_inches='tight')
        img = remove_background_color(Image.open(image_path))
        if result is None:
            img_w, img_h = img.size
            result = Image.new("RGB", (img_w * w, img_h * h))
            result_mask = Image.new("RGB", (img_w * w, img_h * h))
        coords_x = (i // h) * img_w
        coords_y = (i % h) * img_h
        result.paste(img, (coords_x, coords_y, coords_x + img_w, coords_y + img_h))
        img_mask = remove_background_color(Image.open(mask_path))
        result_mask.paste(img_mask, (coords_x, coords_y, coords_x + img_w, coords_y + img_h))
    result.save("{}/{}.png".format(folder, "all_patients"))
    result_mask.save("{}/{}.png".format(folder, "all_patients_masked"))
    gif_list = [np.array(result)] * 5 + [np.array(result_mask)]
    imageio.mimsave("{}/{}.gif".format(folder, "all_patients"), gif_list, duration=0.4)
    plt.close("all")


def main():
    """Load dataset and print statistics."""
    # Parse arguments
    args = parse_arguments()

    # Load dataset
    dataset_location = args.dataset
    if not os.path.exists(dataset_location) and not dataset_location.startswith("data/"):
        dataset_location = "data/{}".format(dataset_location)
    x_whole, y_whole, mask_whole, patients_whole = read_dataset(dataset_location, args.size,
                                                                False, args.plot)
    if args.plot_slices:
        plt.ion()
        for i, (x, y, m, p) in enumerate(zip(x_whole, y_whole, mask_whole, patients_whole)):
            plot_pet_slice(x, mask=m, center=int(x.shape[2] / 2), square_pixels=True,
                           label="Patient {} - Label {}".format(p, int(y[1])))
        plt.ioff()
        plt.close("all")

    if args.save_slices:
        print("Saving Median Slices as Images...")
        save_images_median_slice(x_whole, y_whole, mask_whole, patients_whole)

    if args.plot_volume_histogram:
        volumes = [[], []]
        for x, y, m, p in zip(x_whole, y_whole, mask_whole, patients_whole):
            ones_pos = np.nonzero(m)
            volumes[int(y[1])].append(len(ones_pos[0]))
        volume_factor = 4.07283 * 4.07283 * 5.0 / (10 ** 3)
        print("Volumes Statistics:")
        for i, v in enumerate(volumes):
            v = np.array(v)
            print("Label {}".format(i))
            print("  VOLUME (px)")
            print("  median: {}".format(np.median(v)))
            print("  std:    {}".format(np.std(v)))
            print("  mean:   {}".format(np.mean(v)))
            print("  min:    {}".format(np.min(v)))
            print("  max:    {}".format(np.max(v)))
            print("  VOLUME (cc)")
            print("  median: {}".format(np.median(v * volume_factor)))
            print("  std:    {}".format(np.std(v * volume_factor)))
            print("  mean:   {}".format(np.mean(v * volume_factor)))
            print("  min:    {}".format(np.min(v * volume_factor)))
            print("  max:    {}".format(np.max(v * volume_factor)))
        plt.ion()
        # Units: px
        all_volumes = np.array(volumes[0] + volumes[1])
        y_axis, x_axis, _ = simple_plot_histogram(all_volumes, bins=12, show=True,
                                                  figsize=None, alpha=1, figure=0,
                                                  label_histogram="Histogram",
                                                  axis=(0, None, None, None))
        P = expon.fit(all_volumes)
        rX = np.linspace(0, x_axis[-1] / 12 * 13, 100)
        rP = expon.pdf(rX, *P)
        plt.xlabel("Volume (px)")
        sorted_data = sorted(all_volumes)
        first = int(np.round(len(sorted_data) * 0.1))
        last = int(np.round(len(sorted_data) * 0.9))
        plt.axvline(x=sorted_data[first], color="#eced22", ls="--", lw=2, label="10 % limit")
        plt.axvline(x=sorted_data[last], color="#e62728", ls="--", lw=2, label="90 % limit")
        plt.plot(rX, rP, label="Exponential", lw=2)
        plt.legend()
        # Units: cc
        all_volumes = all_volumes * volume_factor
        y_axis, x_axis, _ = simple_plot_histogram(all_volumes, bins=12, show=True,
                                                  figsize=None, alpha=1, figure=1,
                                                  label_histogram="Histogram",
                                                  axis=(0, None, None, None))
        P = expon.fit(all_volumes)
        rX = np.linspace(0, x_axis[-1] / 12 * 13, 100)
        rP = expon.pdf(rX, *P)
        plt.xlabel("Volume (cc)")
        sorted_data = sorted(all_volumes)
        first = int(np.round(len(sorted_data) * 0.1))
        last = int(np.round(len(sorted_data) * 0.9))
        plt.axvline(x=sorted_data[first], color="#eced22", ls="--", lw=2, label="10 % limit")
        plt.axvline(x=sorted_data[last], color="#e62728", ls="--", lw=2, label="90 % limit")
        plt.plot(rX, rP, label="Exponential", lw=2)
        plt.legend()
        # Boxplots
        figsize = list(plt.rcParams.get('figure.figsize'))
        figsize[0] *= 0.47
        figsize[1] *= 0.8
        widths = 0.5
        plot_boxplot(volumes, figure=2, show=True, window_title="Boxplot Volumes (px)",
                     widths=widths, figsize=figsize)
        plt.ylabel("Volume (px)")
        plt.xlim(0.3, 2.7)  # Brings boxplots closer
        plt.tight_layout()
        plot_boxplot(np.array([np.array(volumes[0]), np.array(volumes[1])]) * volume_factor,
                     figure=3, show=True, window_title="Boxplot Volumes (px)", widths=widths,
                     figsize=figsize)
        plt.ylabel("Volume (cc)")
        plt.xlim(0.3, 2.7)  # Brings boxplots closer
        plt.tight_layout()
        input("Press ENTER to continue ")
        plt.ioff()

    # Calculate statistics
    metrics = [{
        "std": [], "mean": [], "median": [], "surface_to_volume": [],
        "glcm_dissimilarity": [], "glcm_correlation": [], "glcm_asm": []
    }, {
        "std": [], "mean": [], "median": [], "surface_to_volume": [],
        "glcm_dissimilarity": [], "glcm_correlation": [], "glcm_asm": []
    }]
    patients = set()
    gray_values = [[], []]
    masked_gray_values = [[], []]
    dataset_x = []
    dataset_y = []
    dataset_info = ""
    biased_data = False
    for i, (x, y, m, p) in enumerate(zip(x_whole, y_whole, mask_whole, patients_whole)):
        if p in patients and not biased_data:
            input("Repeated patient '{}'. This should never happen.".format(p))
            input("This message won't be displayed again, but know that the data may be biased"
                  " towards some specific patients.")
            biased_data = True
        if args.factor:
            x = x * 255
        patients.add(p)
        label = int(y[1])
        std_dev = np.std(x)
        mean = np.mean(x)
        median = np.median(x)
        surface, volume, mask_positions = get_statistics_mask(m)
        surf_to_vol = surface / volume
        dissimilarity, correlation, asm = get_glcm_statistics(x)
        gray_values[label].extend(list(x.flatten()))
        masked_gray_values[label].extend(list(x[mask_positions]))
        if args.verbose:
            print("Label:              {}".format(label))
            print("Mean:               {}".format(mean))
            print("Median:             {}".format(median))
            print("Std:                {}".format(std_dev))
            print("Surface to Volume:  {} (S: {}, V: {})".format(surf_to_vol, surface, volume))
            print("GLCM dissimilarity: {}".format(dissimilarity))
            print("GLCM correlation:   {}".format(correlation))
            print("GLCM asm:           {}".format(asm))
            print(" ")
        metrics[label]["std"].append(std_dev)
        metrics[label]["mean"].append(mean)
        metrics[label]["median"].append(median)
        metrics[label]["surface_to_volume"].append(surf_to_vol)
        metrics[label]["glcm_dissimilarity"].append(dissimilarity)
        metrics[label]["glcm_correlation"].append(correlation)
        metrics[label]["glcm_asm"].append(asm)
        if args.save_dataset:
            dataset_info = "mean_std_volume"
            dataset_x.append([mean, std_dev, volume])
            dataset_y.append(label)

    # Calculate how different samples are
    print("KS_2SAMP similarity for masked pixels only:")
    calculate_similarity(masked_gray_values[0], masked_gray_values[1])
    print(" ")
    print("KS_2SAMP similarity for all pixels:")
    calculate_similarity(gray_values[0], gray_values[1])
    print(" ")

    if args.save_dataset:
        dataset_x = np.array(dataset_x)
        dataset_y = np.array(dataset_y)
        print("Saving dataset with the following characteristics:")
        print("    Data saved: {}".format(dataset_info))
        print("    X shape:    {}".format(dataset_x.shape))
        print("    Y shape:    {}".format(dataset_y.shape))
        dataset_name = "features_dataset_{}_{}".format(dataset_info, dataset_location)
        np.savez(dataset_name, x=dataset_x, y=dataset_y)
        print("Dataset saved in: '{}.npz'\n".format(dataset_name))

    # Create figures of metrics that will be saved and/or plotted
    f = 0
    plot_metric(metrics[0]["std"], metrics[1]["std"], label0="Std Dev Label 0",
                label1="Std Dev Label 1", label_all="Std Dev Labels 0 and 1",
                figure=f, plot_data=args.plot, window_histogram="Histogram Std Dev",
                window_boxplot="Boxplot Std Dev")
    f = 2
    plot_metric(metrics[0]["mean"], metrics[1]["mean"], label0="Mean Label 0",
                label1="Mean Label 1", label_all="Mean Labels 0 and 1",
                figure=f, plot_data=args.plot, window_histogram="Histogram Mean",
                window_boxplot="Boxplot Mean")
    f = 4
    plot_metric(metrics[0]["median"], metrics[1]["median"], label0="Median Label 0",
                label1="Median Label 1", label_all="Median Labels 0 and 1",
                figure=f, plot_data=args.plot, window_histogram="Histogram Median",
                window_boxplot="Boxplot Median")
    f = 6
    plot_metric(metrics[0]["surface_to_volume"], metrics[1]["surface_to_volume"],
                label0="Surface to Volume Ratio Label 0",
                label1="Surface to Volume Ratio Label 1",
                label_all="Surface to Volume Ratio Labels 0 and 1",
                figure=f, plot_data=args.plot,
                window_histogram="Histogram Surface to Volume Ratio",
                window_boxplot="Boxplot Surface to Volume Ratio")
    f = 8
    plot_metric(metrics[0]["glcm_dissimilarity"], metrics[1]["glcm_dissimilarity"],
                label0="GLCM Dissimilarity Label 0",
                label1="GLCM Dissimilarity Label 1",
                label_all="GLCM Dissimilarity Labels 0 and 1",
                figure=f, plot_data=args.plot,
                window_histogram="Histogram GLCM Dissimilarity",
                window_boxplot="Boxplot GLCM Dissimilarity")
    f = 10
    plot_metric(metrics[0]["glcm_correlation"], metrics[1]["glcm_correlation"],
                label0="GLCM Correlation Label 0",
                label1="GLCM Correlation Label 1",
                label_all="GLCM Correlation Labels 0 and 1",
                figure=f, plot_data=args.plot,
                window_histogram="Histogram GLCM Correlation",
                window_boxplot="Boxplot GLCM Correlation")
    f = 12
    plot_metric(metrics[0]["glcm_asm"], metrics[1]["glcm_asm"],
                label0="GLCM ASM Label 0",
                label1="GLCM ASM Label 1",
                label_all="GLCM ASM Labels 0 and 1",
                figure=f, plot_data=args.plot,
                window_histogram="Histogram GLCM ASM",
                window_boxplot="Boxplot GLCM ASM")
    if not args.dry_run:
        print("Saving figures ...")
        save_plt_figures_to_pdf("{}/statistics.pdf".format(dataset_location), verbose=True)
    if args.plot:
        input("Press ENTER to close all figures and continue.")
    plt.close("all")

    # Create figures of intensities that will be saved and/or plotted
    f = 14
    plot_metric(masked_gray_values[0], masked_gray_values[1],
                label0="Tumor Intensities Label 0",
                label1="Tumor Intensities Label 1",
                label_all="Tumor Intensities Labels 0 and 1",
                figure=f, plot_data=args.plot,
                window_histogram="Histogram Intensities",
                window_boxplot="Boxplot Intensities",
                simple_histograms=True, one_histogram=True)
    f = 16
    plot_metric(gray_values[0], gray_values[1],
                label0="Whole Box Intensities Label 0",
                label1="Whole Box Intensities Label 1",
                label_all="Whole Box Intensities Labels 0 and 1",
                figure=f, plot_data=args.plot,
                window_histogram="Histogram Intensities",
                window_boxplot="Boxplot Intensities",
                simple_histograms=True, one_histogram=True)
    if not args.dry_run:
        print("Saving figures ...")
        save_plt_figures_to_pdf("{}/intensities.pdf".format(dataset_location), verbose=True)
    if args.plot:
        input("Press ENTER to close all figures and continue.")
        plt.close("all")
    print("For more detailed printed statistics, run 'calculate_labels_differences.py'")


if __name__ == "__main__":
    main()
